# aflify
This tool can be used to build arbitrary software with added AFL instrumentation.
To archive this, a new mount namespace is created and the gcc and clang binaries
are redirected to this script by utilizing bind mounts.

As mount namespaces require root access, this script will prompt for the
sudo password. However, the compilation process will not be done with elevated
privileges as long as this script itself is not executed with these.

Besides using the command line flags, you might also set the following environment variables:
 - AFLIFY_CFLAGS: To add flags to the compiler calls.
 - AFLIFY_STRIP_CFLAGS: To stript flags from the compiler calls.

Examples:
aflify make -j 8
aflify cmake .. && make -j8