#! /usr/bin/env python3

import argparse
import logging
import os
import shlex
import textwrap

from depthcharge_tools import __version__
from depthcharge_tools.mkdepthcharge import mkdepthcharge
from depthcharge_tools.utils import (
    root_requires_initramfs,
    vboot_keys,
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

    @Group
    def positionals(self):
        """Positional arguments"""

    @positionals.add
    @Argument
    def kernel_version(self, kernel_version=None):
        """Installed kernel version to build an image for."""

        if kernel_version is not None:
            kernels = [
                k for k in Kernel.all()
                if k.release == kernel_version
            ]
            if not kernels:
                raise ValueError(
                    "Could not find an installed kernel for version '{}'."
                    .format(kernel_version)
                )
            kernel = kernels[0]

        else:
            kernel = max(Kernel.all())

        return kernel

    @property
    def config_section(self):
        parser = self.config
        section_name = "depthchargectl/build"

        if section_name not in parser.sections():
            parser.add_section(section_name)
        return self.config[section_name]

    @property
    def kernel_cmdline(self):
        cmdline = self.config_section.get("kernel-cmdline")
        if cmdline is not None:
            return shlex.split(cmdline)

    @property
    def kernel_compression(self):
        compress = self.config_section.get("kernel-compression")
        if compress is not None:
            return compress.split(" ")

    @property
    def ignore_initramfs(self):
        return self.config_section.getboolean("ignore-initramfs", False)

    def __call__(self):
        try:
            logger.info(
                "Building images for board '{}' ('{}')."
                .format(self.board_name, self.board_codename)
            )
        except KeyError:
            raise ValueError(
                "Cannot build images for unsupported board '{}'."
                .format(self.board)
            )

        k = self.kernel_version
        logger.info(
            "Building for kernel version '{}'.".format(k.release)
        )

        # vmlinuz is always mandatory
        if k.kernel is None:
            raise ValueError(
                "No vmlinuz file found for version '{}'."
                .format(k.release)
            )

        # Initramfs is optional.
        if k.initrd is None:
            logger.info(
                "No initramfs file found for version '{}'."
                .format(k.release)
            )

        # Device trees are optional based on board configuration.
        if self.board_dtb_name is not None:
            if self.board_image_format == "fit":
                if k.fdtdir is None:
                    raise ValueError(
                        "No dtb directory found for version '{}', "
                        "but this machine needs a dtb."
                        .format(k.release)
                    )

                dtbs = sorted(k.fdtdir.glob(
                    "**/{}".format(self.board_dtb_name)
                ))

                if not dtbs:
                    raise ValueError(
                        "No dtb file '{}' found in '{}'."
                        .format(self.board_dtb_name, k.fdtdir)
                    )

            elif self.board_image_format == "zimage":
                raise ValueError(
                    "Image format '{}' doesn't support dtb files "
                    "('{}') required by your board."
                    .format(self.board_image_format, self.board_dtb_name)
                )

        # On at least Debian, the root the system should boot from
        # is included in the initramfs. Custom kernels might still
        # be able to boot without an initramfs, but we need to
        # inject a root= parameter for that.
        cmdline = self.kernel_cmdline or []
        for c in cmdline:
            lhs, _, rhs = c.partition("=")
            if lhs.lower() == "root":
                root = rhs
                logger.info(
                    "Using root as set in user configured cmdline."
                )
                break
        else:
            logger.info("Trying to prepend root into cmdline.")
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

            # Prepend it so that user-given cmdline overrides it.
            logger.info(
                "Prepending 'root={}' to kernel cmdline."
                .format(root)
            )
            cmdline.append("root={}".format(root))

        if self.ignore_initramfs:
            logger.warn(
                "Ignoring initramfs '{}' as configured, "
                "appending 'noinitrd' to the kernel cmdline."
                .format(k.initrd)
            )
            k.initrd = None
            cmdline.append("noinitrd")

        # Linux kernel without an initramfs only supports certain
        # types of root parameters, check for them.
        if k.initrd is None and root_requires_initramfs(root):
            raise ValueError(
                "An initramfs is required for root '{}'."
                .format(root)
            )

        # Default to OS-distributed keys, override with custom
        # values if given.
        _, keyblock, signprivate, signpubkey = vboot_keys()
        if self.vboot_keyblock is not None:
            keyblock = self.vboot_keyblock
        if self.vboot_private_key is not None:
            signprivate = self.vboot_private_key
        if self.vboot_public_key is not None:
            signpubkey = self.vboot_public_key

        # Allowed compression levels. We will call mkdepthcharge by
        # hand multiple times for these.
        compress = (
            self.kernel_compression
            or self.board_kernel_compression
            or ["none"]
        )
        for c in compress:
            if c != "none" and c not in self.board_kernel_compression:
                raise ValueError(
                    "Configured to use compression '{}', but this "
                    "board does not support it."
                    .format(c)
                )

        # zimage doesn't support compression
        if self.board_image_format == "zimage":
            if compress != ["none"]:
                raise ValueError(
                    "Image format '{}' doesn't support kernel "
                    "compression formats '{}'."
                    .format(self.board_image_format, compress)
                )

        # Try to keep the output reproducible. Initramfs date is
        # bound to be later than vmlinuz date, so prefer that if
        # possible.
        if "SOURCE_DATE_EPOCH" not in os.environ:
            if k.initrd is not None:
                date = int(k.initrd.stat().st_mtime)
            else:
                date = int(k.kernel.stat().st_mtime)

            if date:
                os.environ["SOURCE_DATE_EPOCH"] = str(date)
            else:
                logger.error(
                    "Couldn't determine a date from initramfs "
                    "nor vmlinuz."
                )

        # Keep images in their own directory, which might not be
        # created at install-time
        images = Path("/tmp/boot/depthcharge-tools/images")
        os.makedirs(images, exist_ok=True)

        # Build to temporary files so we do not overwrite existing
        # images with an unbootable image.
        output = images / "{}.img".format(k.release)
        outtmp = images / "{}.img.tmp".format(k.release)

        for c in compress:
            logger.info("Trying with compression '{}'.".format(c))
            mkdepthcharge(
                cmdline=cmdline,
                compress=(c if c != "none" else None),
                dtbs=dtbs,
                image_format=self.board_image_format,
                initramfs=k.initrd,
                keyblock=keyblock,
                name=k.description,
                output=outtmp,
                signprivate=signprivate,
                vmlinuz=k.kernel,
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
                    .format(c)
                )
                if c != compress[-1]:
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
        outtmp.copy_to(output)
        outtmp.unlink()

        logger.info(
            "Built image for kernel version '{}'."
            .format(k.release)
        )
        return output

    global_options = depthchargectl.global_options

