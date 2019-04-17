#!/bin/python3

import argparse
import ctypes
import os
import subprocess
import sys
from ctypes import c_int
from ctypes.util import find_library

LIBC_PATH = find_library('c')
if not LIBC_PATH:
    print("Failed to find libc!")
    exit(1)

LIBC = ctypes.cdll.LoadLibrary(LIBC_PATH)

LIBC.unshare.argtypes = [c_int]
LIBC.unshare.restype = c_int
CLONE_NEWNS = 0x00020000

OWN_PATH = os.path.abspath(__file__)

DESCRIPTION = """
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
"""

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def msg(msg):
    print(f"{bcolors.OKGREEN}{bcolors.BOLD}[aflify] {msg}{bcolors.ENDC}")

def err(msg):
    print(f"{bcolors.FAIL}{bcolors.BOLD}[aflify] {msg}{bcolors.ENDC}")

def unsharens():
    try:
        LIBC.unshare(CLONE_NEWNS)
    except Exception as e:
        err(f"Unsharing the mount namespace failed, check your system!\n{e}")
        exit(1)

def unbind_mount_file(path):
    subprocess.check_call(['umount', path])

def bind_mount_file(file_path, dst_path):
    #subprocess.check_call(['mount', '--make-private', '/'])
    subprocess.check_call(['mount', '--bind', '--make-private', file_path, dst_path])

REDIRECTED_BINS = [
    '/usr/bin/gcc',
    '/usr/bin/clang',
    '/usr/bin/strip'
]

def remove_redirects():
    for f in REDIRECTED_BINS:
        unbind_mount_file(f)

def setup_redirects():
    for f in REDIRECTED_BINS:
        bind_mount_file(OWN_PATH, f)

def drop_privileges():
    grps = [int(e) for e in os.environ['AFLIFY_GROUP_IDS'].split(',')]
    os.setgroups(grps)
    os.setgid(int(os.environ['AFLIFY_GID']))
    os.setuid(int(os.environ['AFLIFY_UID']))

def strip_flags(args):
    stripped_flags = os.environ['AFLIFY_STRIP_CFLAGS'].split(' ')
    return list(filter(lambda e: e not in stripped_flags, args))

def get_cflags():
    return os.environ['AFLIFY_CFLAGS'].split(' ')

def clang_wrapper():
    args = sys.argv[1:]

    args = strip_flags(args)
    args = get_cflags() + args

    unsharens()
    remove_redirects()
    drop_privileges()
    subprocess.Popen(" ".join([os.environ['AFLIFY_CLANG']] + args), shell=True).wait()


def gcc_wrapper():
    args = sys.argv[1:]

    args = strip_flags(args)
    args = get_cflags() + args

    unsharens()
    remove_redirects()
    drop_privileges()
    subprocess.Popen(" ".join([os.environ['AFLIFY_GCC']] + args), shell=True).wait()

def strip_wrapper():
    drop_privileges()
    msg("Call to strip blocked")

def main():
    #TODO: ccache

    #We need to real root for mount
    if os.getuid() != 0:
        #Save real uid, gid,..., so we can later change back to the user who called us
        r, e, s = os.getresuid()
        rg, eg, sg = os.getresgid()
        os.environ['AFLIFY_UID'] = str(r)
        os.environ['AFLIFY_GID'] = str(rg)
        grps = os.getgroups()
        grps = [str(e) for e in grps]
        os.environ['AFLIFY_GROUP_IDS'] = ','.join(grps)
        return subprocess.Popen('sudo ' + '-E ' + ' '.join(sys.argv), shell=True).wait()

    #Make cc point to gcc or clang
    if os.path.islink(sys.argv[0]):
        sys.argv[0] = os.readlink(sys.argv[0])

    basename = os.path.basename(sys.argv[0])

    if basename == 'gcc':
        #Intercept gcc calls
        msg("GCC intercepted")
        return gcc_wrapper()
    elif basename == 'clang':
        #Intercept clang calls
        msg("clang intercepted")
        return clang_wrapper()
    elif basename == 'strip':
        #Intercept strip calls
        return strip_wrapper()

    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gcc-to', dest='gcc', default='afl-clang-fast', help='Target to which gcc calls are redirected to (default afl-clang-fast)')
    parser.add_argument('--clang-to', dest='clang', default='afl-clang-fast', help='Target to which clang calls are redirected to (default afl-clang-fast)')
    parser.add_argument('command', type=str, help='The application to execute (e.g., make, cmake, ...)')
    parser.add_argument('args', nargs=argparse.REMAINDER, help='Arguments for the target application')
    args = parser.parse_args()

    os.environ['AFLIFY_GCC'] = args.gcc
    os.environ['AFLIFY_CLANG'] = args.clang

    if 'AFLIFY_CFLAGS' not in os.environ:
        os.environ['AFLIFY_CFLAGS'] = " ".join(['-g'])
    if 'AFLIFY_STRIP_CFLAGS' not in os.environ:
        os.environ['AFLIFY_STRIP_CFLAGS'] = " ".join(['-x03', '-s'])

    msg(f'AFLIFY_CFLAGS="{os.environ["AFLIFY_CFLAGS"]}"')
    msg(f'AFLIFY_STRIP_CFLAGS="{os.environ["AFLIFY_STRIP_CFLAGS"]}"')

    #Separate mount namespace from the calling process
    unsharens()

    #Disables propagation of mounts to other namespaces
    subprocess.check_call(['mount', '--make-rprivate', '/'])

    #Redirect wrappen programs (e.g., gcc, clang, strip) to this script
    setup_redirects()

    #Dont execute the target command and subcommands as root.
    #If one of the wrapped programs is called, we will regain root privileges
    drop_privileges()

    p = subprocess.Popen(" ".join([args.command] + args.args), shell=True)
    p.wait()


if __name__ == "__main__":
    main()
