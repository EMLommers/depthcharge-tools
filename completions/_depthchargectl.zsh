#compdef depthchargectl

function _depthchargectl {
    _arguments -C \
        {-h,--help}'[Show a help message.]' \
        {-v,--verbose}'[Print more detailed output.]' \
        {-V,--version}'[Print program version.]' \
        --tmpdir'[Directory to keep temporary files.]:temp dir:_directories' \
        --config'[Additional configuration file to read]:config file:_files' \
        --board'[Assume running on the specified board]:board codenames:{_depthchargectl__board;}' \
        --images-dir'[Directory to store built images]:images dir:_directories' \
        --vboot-keyblock'[Keyblock file to include in images]:keyblock file:_files' \
        --vboot-public-key'[Public key file to verify images]:vbpubk file:_files' \
        --vboot-private-key'[Private key file to include in images]:vbprivk file:_files' \
        --kernel-cmdline'[Command line options for the kernel]:kernel cmdline:{_depthchargectl__cmdline;}' \
        --ignore-initramfs'[Do not include initramfs in images]' \
        '1:command:(bless build config check list remove target write)' \
        '*::arg:->args' \
        ;

    case "$state:$line[1]" in
        args:bless)
            _arguments -S \
                --bad'[Set the partition as unbootable]' \
                --oneshot'[Set the partition to be tried once]' \
                {-i,--partno}'[Partition number in the given disk image]:number:()' \
                ':disk or partition:{_depthchargectl__disk}' \
                ;
            ;;
        args:build)
            _arguments -S \
                --description'[Human-readable description for the image]:image description:($(source /etc/os-release; echo "$NAME"))' \
                --root'[Root device to add to kernel cmdline]:root device:{_depthchargectl__root; _depthchargectl__disk}' \
                --compress'[Compression types to attempt]:compress:(none lz4 lzma)' \
                --timestamp'[Build timestamp for the image]:timestamp:($(date "+%s"))' \
                {-o,--output}'[Output image to path instead of storing in images-dir]:output path:_files' \
                --kernel-release'[Release name for the kernel used in image name]:kernel release:{_depthchargectl__kernel;}' \
                --kernel'[Kernel executable]:kernel:_files' \
                --initramfs'[Ramdisk image]:initramfs:_files' \
                --fdtdir'[Directory to search device-tree binaries for the board]:fdtdir:_directories' \
                --dtbs'[Device-tree binary files to use instead of searching fdtdir]:dtb files:_files' \
                ':kernel version:{_depthchargectl__kernel}' \
                ;
            ;;
        args:config)
            _arguments -S \
                --section'[Config section to work on.]' \
                --default'[Value to return if key does not exist in section.]' \
                ':config key:' \
                ;
            ;;
        args:check)
            _arguments -S \
                ':image file:_files' \
                ;
            ;;
        args:list)
            local outputspec='{_values -s , "description" "A" "ATTRIBUTE" "S" "SUCCESSFUL" "T" "TRIES" "P" "PRIORITY" "PATH" "DISKPATH" "DISK" "PARTNO" "SIZE"}'
            _arguments -S \
                {-n,--noheadings}'[Do not print column headings.]' \
                {-a,--all-disks}'[list partitions on all disks.]' \
                {-o,--output}'[Comma separated list of columns to output.]:columns:'"$outputspec" \
                '*::disk or partition:{_depthchargectl__disk}' \
                ;
            ;;
        args:remove)
            _arguments -S \
                {-f,--force}'[Allow disabling the current partition.]' \
                '::kernel version or image file:{_depthchargectl__kernel; _files}' \
                ;
            ;;
        args:target)
            _arguments -S \
                {-s,--min-bytes}'[Target partitions larger than this size.]:bytes:(16777216 33554432)' \
                --allow-current'[Allow targeting the currently booted part.]' \
                '*::disk or partition:{_depthchargectl__disk}' \
                ;
            ;;
        args:write)
            _arguments -S \
                {-f,--force}'[Write image even if it cannot be verified.]' \
                {-t,--target}'[Specify a disk or partition to write to.]:disk or partition:{_depthchargectl__disk}' \
                --no-prioritize'[Do not set any flags on the partition]' \
                --allow-current'[Allow overwriting the current partition]' \
                '::kernel version or image file:{_depthchargectl__kernel; _files}' \
                ;
            ;;
        *) : ;;
    esac

}

function _depthchargectl__kernel {
    if command -v linux-version >/dev/null 2>/dev/null; then
        local kversions=($(linux-version list))
        _describe 'kernel version' kversions
    fi
}

function _depthchargectl__disk {
    local disks=($(lsblk -o "PATH" -n -l))
    _describe 'disk or partition' disks
}

function _depthchargectl__board {
    local script=(
        'import re;'
        'from depthcharge_tools import boards_ini;'
        'boards = re.findall("codename = (.+)", boards_ini);'
        'print(*sorted(boards));'
    )
    local boards=($(python3 -c "$script"))
    _describe 'board codenames' boards
}

function _depthchargectl__cmdline {
    local cmdline=($(cat /proc/cmdline | sed -e 's/\(cros_secure\|kern_guid\)[^ ]* //g'))
    _describe 'kernel cmdline' cmdline
}

function _depthchargectl__root {
    local root=($(findmnt --fstab -n -o SOURCE "/"))
    _describe root root
}

_depthchargectl "$@"
