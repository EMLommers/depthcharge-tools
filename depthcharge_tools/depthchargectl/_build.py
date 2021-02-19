#! /usr/bin/env python3

import argparse
import logging
import os
import shlex
import textwrap

from depthcharge_tools import __version__
from depthcharge_tools.mkdepthcharge import mkdepthcharge
from depthcharge_tools.utils import (
    installed_kernels,
    root_requires_initramfs,
    Disk,
    Partition,
    Path,
    Kernel,
    Command,
    Argument,
    Group,
    findmnt,
    sha256sum,
)

from depthcharge_tools.depthchargectl import depthchargectl

logger = logging.getLogger(__name__)


@depthchargectl.subcommand("build")
class depthchargectl_build(
    depthchargectl,
    prog="depthchargectl build",
    usage="%(prog)s [options] [KERNEL_VERSION]",
    add_help=False,
):
    """Buld a depthcharge image for the running system."""

    config_section = "depthchargectl/build"

    @Group
    def positionals(self):
        """Positional arguments"""

    @positionals.add
    @Argument
    def kernel_version(self, kernel_version=None):
        """Installed kernel version to build an image for."""
        kernels = installed_kernels()

        if isinstance(kernel_version, str):
            kernels = [
                k for k in kernels
                if k.release == kernel_version
            ]
            if not kernels:
                raise ValueError(
                    "Could not find an installed kernel for version '{}'."
                    .format(kernel_version)
                )
            kernel = kernels[0]

        elif kernels:
            kernel = max(kernels)

        return kernel

    @Group
    def options(self):
        """Options"""

    @Group
    def custom_kernel_options(self):
        """Custom kernel specification"""

    @custom_kernel_options.add
    @Argument("--kernel-release", nargs=1)
    def kernel_release(self, name=None):
        """Release name for the kernel used in image name"""
        if name is None:
            name = self.kernel_version.release

        return name

    @custom_kernel_options.add
    @Argument("--kernel", nargs=1)
    def kernel(self, file_=None):
        """Kernel executable"""
        if file_ is None:
            file_ = self.kernel_version.kernel

        # vmlinuz is always mandatory
        if file_ is None:
            raise ValueError(
                "No vmlinuz file found for version '{}'."
                .format(self.kernel_release)
            )

        return file_

    @custom_kernel_options.add
    @Argument("--initramfs", nargs=1)
    def initrd(self, file_=None):
        """Ramdisk image"""
        if file_ is None:
            file_ = self.kernel_version.initrd

        if self.ignore_initramfs:
            logger.warn(
                "Ignoring initramfs '{}' as configured."
                .format(file_)
            )
            return None

        # Initramfs is optional.
        if file_ is None:
            logger.info(
                "No initramfs file found for version '{}'."
                .format(self.kernel_release)
            )

        return file_

    @custom_kernel_options.add
    @Argument("--fdtdir", nargs=1)
    def fdtdir(self, dir_=None):
        """Directory to search device-tree binaries for the board"""
        if dir_ is None:
            dir_ = self.kernel_version.fdtdir

        return dir_

    @custom_kernel_options.add
    @Argument("--dtbs", nargs="+", metavar="FILE")
    def dtbs(self, *files):
        """Device-tree binary files to use instead of searching fdtdir"""

        # Device trees are optional based on board configuration.
        if self.board.dtb_name is not None and len(files) == 0:
            if self.fdtdir is None:
                raise ValueError(
                    "No dtb directory found for version '{}', "
                    "but this machine needs a dtb."
                    .format(self.kernel_release)
                )

            files = sorted(self.fdtdir.glob(
                "**/{}".format(self.board.dtb_name)
            ))

            if len(files) == 0:
                raise ValueError(
                    "No dtb file '{}' found in '{}'."
                    .format(self.board.dtb_name, self.fdtdir)
                )

        if self.board.image_format == "zimage" and len(files) != 0:
            raise ValueError(
                "Image format '{}' doesn't support dtb files."
                .format(self.board.image_format)
            )

        return files

    @options.add
    @Argument("--description", nargs=1)
    def description(self, desc=None):
        """Human-readable description for the image"""
        if desc is None:
            desc = self.kernel_version.description

        return desc

    @options.add
    @Argument("--root", nargs=1)
    def root(self, root=None):
        """Root device to add to kernel cmdline"""
        if root is None:
            cmdline = self.kernel_cmdline or []
            for c in cmdline:
                lhs, _, rhs = c.partition("=")
                if lhs.lower() == "root":
                    root = rhs
                    logger.info(
                        "Using root as set in user configured cmdline."
                    )

        if root is None:
            logger.info("Trying to figure out a root for cmdline.")
            root = findmnt.fstab("/").stdout.rstrip("\n")

            if root:
                logger.info("Using root as set in /etc/fstab.")
            else:
                logger.warn(
                    "Couldn't figure out a root cmdline parameter from "
                    "/etc/fstab. Will use '{}' from kernel."
                    .format(root)
                )
                root = findmnt.kernel("/").stdout.rstrip("\n")

        if not root:
            raise ValueError(
                "Couldn't figure out a root cmdline parameter."
            )

        return root

    # This should be overriding kernel_cmdline from the parent instead...
    @property
    def cmdline(self):
        cmdline = self.kernel_cmdline or []

        # On at least Debian, the root the system should boot from
        # is included in the initramfs. Custom kernels might still
        # be able to boot without an initramfs, but we need to
        # inject a root= parameter for that.
        if 'root={}'.format(self.root) not in cmdline:
            logger.info(
                "Prepending 'root={}' to kernel cmdline."
                .format(self.root)
            )
            cmdline.append("root={}".format(self.root))

        if self.ignore_initramfs:
            logger.warn(
                "Ignoring initramfs as configured, "
                "appending 'noinitrd' to the kernel cmdline."
                .format(self.initrd)
            )
            cmdline.append("noinitrd")

        # Linux kernel without an initramfs only supports certain
        # types of root parameters, check for them.
        if self.initrd is None and root_requires_initramfs(self.root):
            raise ValueError(
                "An initramfs is required for root '{}'."
                .format(self.root)
            )

        return cmdline

    @options.add
    @Argument("--compress", nargs="+", metavar="TYPE")
    def compress(self, *compress):
        """Compression types to attempt."""

        # Allowed compression levels. We will call mkdepthcharge by
        # hand multiple times for these.
        for c in compress:
            if c not in ("none", "lz4", "lzma"):
                raise ValueError(
                    "Unsupported compression type '{}'."
                    .format(t)
                )

        if len(compress) == 0:
            compress = ["none"]
            if self.board.boots_lz4_kernel:
                compress += ["lz4"]
            if self.board.boots_lzma_kernel:
                compress += ["lzma"]

            # zimage doesn't support compression
            if self.board.image_format == "zimage":
                compress = ["none"]

        return compress

    @options.add
    @Argument("--timestamp", nargs=1)
    def timestamp(self, seconds=None):
        """Build timestamp for the image"""
        if seconds is None:
            if "SOURCE_DATE_EPOCH" in os.environ:
                seconds = os.environ["SOURCE_DATE_EPOCH"]

        # Initramfs date is bound to be later than vmlinuz date, so
        # prefer that if possible.
        if seconds is None:
            if self.initrd is not None:
                seconds = int(self.initrd.stat().st_mtime)
            else:
                seconds = int(self.kernel.stat().st_mtime)

        if seconds is None:
            logger.error(
                "Couldn't determine a timestamp from initramfs "
                "nor vmlinuz."
            )

        return seconds

    @options.add
    @Argument("--output", nargs=1)
    def output(self, path=None):
        """Output image to path instead of storing in images-dir"""
        if path is None:
            path = self.images_dir / "{}.img".format(self.kernel_release)

        return Path(path)

    def __call__(self):
        try:
            logger.info(
                "Building images for board '{}' ('{}')."
                .format(self.board.name, self.board.codename)
            )
        except KeyError:
            raise ValueError(
                "Cannot build images for unsupported board '{}'."
                .format(self.board)
            )

        logger.info(
            "Building for kernel version '{}'."
            .format(self.kernel_release)
        )

        # Images dir might not have been created at install-time
        os.makedirs(self.output.parent, exist_ok=True)

        # Build to a temporary file so we do not overwrite existing
        # images with an unbootable image.
        outtmp = self.output.parent / "{}.tmp".format(self.output.name)

        # Try to keep output reproducible.
        if self.timestamp is not None:
            os.environ["SOURCE_DATE_EPOCH"] = str(self.timestamp)

        for compress in self.compress:
            logger.info("Trying with compression '{}'.".format(compress))
            mkdepthcharge(
                cmdline=self.cmdline,
                compress=compress,
                dtbs=self.dtbs,
                image_format=self.board.image_format,
                initramfs=self.initrd,
                keyblock=self.vboot_keyblock,
                name=self.description,
                output=outtmp,
                signprivate=self.vboot_private_key,
                vmlinuz=self.kernel,
            )

            try:
                depthchargectl.check(image=outtmp)
                break
            except OSError as err:
                if err.errno != 3:
                    raise RuntimeError(
                        "Failed while creating depthcharge image."
                    )
                logger.warn(
                    "Image with compression '{}' is too big "
                    "for this board."
                    .format(compress)
                )
                if compress != self.compress[-1]:
                    continue
                logger.error(
                    "The initramfs might be too big for this machine. "
                    "Usually this can be resolved by including less "
                    "modules in the initramfs and/or compressing it "
                    "with a better algorithm. Please check your distro's "
                    "documentation for how to do this."
                )
                raise RuntimeError(
                    "Couldn't build a small enough image for this machine."
                )
        else:
            raise RuntimeError(
                "Failed to create a valid depthcharge image."
            )

        logger.info("Copying newly built image and info to output.")
        outtmp.copy_to(self.output)
        outtmp.unlink()

        logger.info(
            "Built image for kernel version '{}'."
            .format(self.kernel_release)
        )
        return self.output

    global_options = depthchargectl.global_options
    config_options = depthchargectl.config_options
