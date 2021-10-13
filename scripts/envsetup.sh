# Copyright (C) 2018 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

gettop() {
    # $BASH_SOURCE works if the shell is bash. $0 works when the shell was
    # invoked from a shell script but may fail when sourced in non-bash shell.
    SCRIPT=$(readlink -f ${BASH_SOURCE:-$0})
    TOPFILE="trusty/vendor/google/aosp/scripts/envsetup.sh"
    TOPDIR=$(dirname $SCRIPT)
    while [ \( ! -f "$TOPDIR/$TOPFILE" \) -a \( "$TOPDIR" != "/" \) ]; do
        TOPDIR=`dirname $TOPDIR`
    done
    if [ ! -f "$TOPDIR/$TOPFILE" ]; then
        echo "Error: Couldn't locate the top of the trusty tree. Try using bash?" 1>&2
        exit 1
    fi
    echo $TOPDIR
}

export TRUSTY_TOP=$(gettop)
export CLANG_BINDIR=${TRUSTY_TOP}/prebuilts/clang/host/linux-x86/clang-r416183c1/bin
export LINUX_CLANG_BINDIR=${TRUSTY_TOP}/prebuilts/clang/host/linux-x86/clang-r433403/bin
export RUST_BINDIR=${TRUSTY_TOP}/prebuilts/rust/linux-x86/1.54.0/bin
export ARCH_arm_TOOLCHAIN_PREFIX=${TRUSTY_TOP}/prebuilts/gcc/linux-x86/arm/arm-linux-androideabi-4.9/bin/arm-linux-androideabi-
export ARCH_arm64_TOOLCHAIN_PREFIX=${TRUSTY_TOP}/prebuilts/gcc/linux-x86/aarch64/aarch64-linux-android-4.9/bin/aarch64-linux-android-
export ARCH_x86_64_TOOLCHAIN_PREFIX=${TRUSTY_TOP}/prebuilts/gcc/linux-x86/x86/x86_64-linux-android-4.9/bin/x86_64-linux-android-
export ARCH_x86_TOOLCHAIN_PREFIX=${TRUSTY_TOP}/prebuilts/gcc/linux-x86/x86/x86_64-linux-android-4.9/bin/x86_64-linux-android-
export BUILDTOOLS_BINDIR=${TRUSTY_TOP}/prebuilts/build-tools/linux-x86/bin
export BUILDTOOLS_COMMON=${TRUSTY_TOP}/prebuilts/build-tools/common
export PY3=$BUILDTOOLS_BINDIR/py3-cmd
