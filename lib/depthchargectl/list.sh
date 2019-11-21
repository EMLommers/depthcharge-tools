# This file is sourced by depthchargectl.

usage() {
cat <<EOF
Usage:
 depthchargectl list [options] [disk ...]

List ChromeOS kernel partitions.

Options:
 -h, --help                 Show this help message.
 -v, --verbose              Print info messages to stderr.
 -n, --noheadings           Don't print column headings.
 -o, --output COLUMNS       Comma separated list of columns to output.

Supported columns:
    SUCCESSFUL (S), TRIES (T), PRIORITY (P), DEVICE
EOF
}


# Parse options and arguments
# ---------------------------

add_column() {
    if has_newline "${1:-}"; then
        usage_error "Newlines not allowed in column names."
    fi

    IFS=","
    case "${1:-}" in
        # Recursively add columns if -o a,b,c given.
        *,*) for c in $1; do add_column "$c"; done; return ;;
        S|SUCCESSFUL) : ;;
        T|TRIES) : ;;
        P|PRIORITY) : ;;
        DEVICE) : ;;
        '') return ;;
        *) usage_error "Unsupported output column '$1'." ;;
    esac
    IFS="$ORIG_IFS"

    info "Adding column: $1"
    COLUMNS="${COLUMNS:-}${COLUMNS:+,}${1}"
}

add_disk() {
    if [ -n "${1:-}" ]; then
        info "Searching disk: $1"
        DISKS="${DISKS:-}${DISKS:+,}${1}"
    fi
}

# Should return number of elemets to shift, never zero.
cmd_args() {
    case "$1" in
        # Options:
        -n|--noheadings)    HEADINGS=no;        return 1 ;;
        -o|--output)        add_column "$2";    return 2 ;;

        # End of options.
        -*) usage_error "Option '$1' not understood." ;;
        *)  add_disk "$1"; return 1 ;;
    esac
}


# Set argument defaults
# ---------------------

cmd_defaults() {
    # Output all columns by default.
    : "${COLUMNS:=SUCCESSFUL,PRIORITY,TRIES,DEVICE}"

    # Add heading by default.
    : "${HEADINGS:=yes}"

    # Can be empty (for all disks) but needs to be set.
    : "${DISKS:=}"

    readonly COLUMNS HEADINGS
    readonly DISKS
}


# Print partition table
# ---------------------

cmd_main() {
    # Columns is comma separated
    IFS=","
    set -- $COLUMNS
    IFS="$ORIG_IFS"

    if [ "$HEADINGS" = "yes" ]; then
        info "Printing headings:"
        for c in "$@"; do
            case "$c" in
                S|SUCCESSFUL)   printf "%-2s " S ;;
                T|TRIES)        printf "%-2s " T ;;
                P|PRIORITY)     printf "%-2s " P ;;
                DEVICE)         printf "%-20s " DEVICE ;;
            esac
        done
        printf "\n"
    fi

    info "Printing table:"
    (
        set -- $DISKS
        depthcharge_parts_table "$@"
    ) | {
        while read -r S P T DEVICE; do
            for c in "$@"; do
                case "$c" in
                    S|SUCCESSFUL)   printf "%-2s "  "$S" ;;
                    T|TRIES)        printf "%-2s "  "$T" ;;
                    P|PRIORITY)     printf "%-2s "  "$P" ;;
                    DEVICE)         printf "%-20s " "$DEVICE" ;;
                esac
            done
            printf "\n"
        done
    }
}
