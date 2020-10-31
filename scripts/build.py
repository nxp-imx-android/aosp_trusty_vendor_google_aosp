#!/bin/sh
"." "`dirname $0`/envsetup.sh"; "exec" "$PY3" "$0" "$@"
#
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
#
"""Invoke trusty build system and run tests."""

import argparse
import getpass
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

import run_tests
import trusty_build_config

script_dir = os.path.dirname(os.path.abspath(__file__))

SDK_README_PATH = "trusty/user/base/sdk/README.md"
DEV_SIGNING_KEY_PATH = "trusty/device/arm/generic-arm64/project/keys/"
DEV_SIGNING_KEY_FILES = [
    "apploader_sign_test_private_key_0.der",
    "apploader_sign_test_public_key_0.der"
]


def get_new_build_id(build_root):
    """Increment build-id file and return new build-id number."""
    path = os.path.join(build_root, "BUILDID")
    try:
        with open(path, "r") as f:
            num = int(f.read()) + 1
    except IOError:
        num = 1
    with open(path, "w") as f:
        f.write(str(num))
        f.truncate()
        # Return buildid string: <user>@<hostname>-<num>
        # Use getpass.getuser() to avoid non-portability/failure of
        # os.getlogin()
        return getpass.getuser() + "@" + os.uname()[1] + "-" + str(num)


def mkdir(path):
    """Create directory including parents if it does not already exist."""
    try:
        os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise


def copy_file(src, dest, optional=False):
    """Copy a file.

    Copy a file or exit if the file cannot be copied.

    Args:
       src: Path of file to copy.
       dest: Path to copy file to.
       optional: Optional boolean argument. If True don't exit if source file
           does not exist.
    """
    if not os.path.exists(src) and optional:
        return
    print("Copy:", repr(src), "->", repr(dest))
    shutil.copy(src, dest)


def archive_build_file(args, project, src, dest=None, optional=False):
    """Copy a file to build archive directory.

    Construct src and dest path and call copy_file.

    Args:
       args: Program arguments.
       project: Project name.
       src: Source path relative to project build dir.
       dest: Optional dest path relative to archive dir. Can be omitted if src
           is a simple filename.
       optional: Optional boolean argument. If True don't exit if source file
           does not exist.
    """
    if not dest:
        dest = src
    src = os.path.join(args.build_root, "build-" + project, src)
    # dest must be a fixed path for repeated builds of the same artifact
    # for compatibility with prebuilt update scripts.
    # Project is fine because that specifies what artifact is being looked
    # for - LK for a specific target.
    # BUILD_ID or feature selections that may change are not, because the
    # prebuilt update script cannot predict the path at which the artifact
    # will live.
    dest = os.path.join(args.archive, project + "." + dest)
    copy_file(src, dest, optional=optional)


def archive_dir(archive, src, dest):
    """Recursively add a directory to a ZIP file.

    Recursively add the src directory to the ZIP with dest path inside the
    archive.

    Args:
       archive: A ZipFile opened for append or write.
       src: Source directory to add to the archive.
       dest: Destination path inside the archive (must be a relative path).
    """
    for root, dirs, files in os.walk(src):
        for f in files:
            file_path = os.path.join(root, f)
            archive_dest = os.path.join(dest, os.path.relpath(file_path, start=src))
            archive.write(file_path, archive_dest)

def archive_file(archive, src_file, dest_dir=""):
    """Add a file to a ZIP file.

    Adds src_file to archive in the directory dest_dir, relative to the root of
    the archive.

    Args:
       archive: A ZipFile opened for append or write.
       src_file: Source file to add to the archive.
       dest_dir: Relative destination path in the archive for this file.
    """
    archive.write(src_file, os.path.join(dest_dir, os.path.basename(src_file)))


def assemble_sdk(args):
    """Assemble Trusty SDK archive"""
    mkdir(args.archive)

    sdk_name = "trusty_sdk-" + args.buildid
    tools_dest = os.path.join(sdk_name, "tools")
    filename = os.path.join(args.archive, sdk_name + ".zip")
    with ZipFile(filename, 'a', compression=ZIP_DEFLATED) as sdk_archive:
        print("Building SDK archive ZIP...")
        for project in args.project:
            project_buildroot = os.path.join(args.build_root, "build-" + project)

            project_sysroot_dir = os.path.join(sdk_name, "sysroots", project, "usr")
            src = os.path.join(project_buildroot, "sdk", "sysroot", "usr")
            archive_dir(sdk_archive, src, project_sysroot_dir)

            src = os.path.join(project_buildroot, "sdk", "LICENSE")
            archive_file(sdk_archive, src, sdk_name)

            src = os.path.join(project_buildroot, "host_tools", "apploader_package_tool")
            archive_file(sdk_archive, src, tools_dest)

            src = os.path.join(project_buildroot, "sdk", "tools", "manifest_compiler.py")
            archive_file(sdk_archive, src, tools_dest)

        # Add AOSP qemu dev signing key.
        for filename in DEV_SIGNING_KEY_FILES:
            archive_file(sdk_archive, os.path.join(DEV_SIGNING_KEY_PATH, filename), tools_dest)

        # Copy SDK README
        archive_file(sdk_archive, SDK_README_PATH, sdk_name)

        # Add clang prebuilt toolchain
        dest = os.path.join(sdk_name, "toolchain", "clang")
        cmd = f"source {os.path.join(script_dir, 'envsetup.sh')} && echo $CLANG_BINDIR"
        clang_bindir = subprocess.check_output(cmd, shell=True, executable="/bin/bash").decode().strip()
        archive_dir(sdk_archive, os.path.join(clang_bindir, ".."), dest)


def build(args):
    """Call build system and copy build files to archive dir."""
    mkdir(args.build_root)
    mkdir(args.archive)

    if args.buildid is None:
        args.buildid = get_new_build_id(args.build_root)
    print("BuildID", args.buildid)

    # build projects
    failed = []

    for project in args.project:
        cmd = "export BUILDROOT=" + args.build_root
        cmd += "; export BUILDID=" + args.buildid
        cmd += "; nice make " + project + " -j " + str(args.jobs)
        # Call envsetup.  If it fails, abort.
        cmd = "source %s && (%s)" % (os.path.join(script_dir, "envsetup.sh"),
                                     cmd)
        status = subprocess.call(cmd, shell=True, executable="/bin/bash")
        print("cmd: '" + cmd + "' returned", status)
        if status:
            failed.append(project)

    if failed:
        print()
        print("some projects have failed to build:")
        print(str(failed))
        sys.exit(1)


def zip_dir(archive, src, dest, filter=lambda _: True):
    """Recursively add a directory to a ZIP file.

    Recursively add the src directory to the ZIP with dest path inside the
    archive.

    Args:
       archive: A ZipFile opened for append or write.
       src: Source directory to add to the archive.
       dest: Destination path inside the archive (must be a relative path).
    """
    for root, _dirs, files in os.walk(src):
        for f in files:
            if not filter(f):
                continue
            file_path = os.path.join(root, f)
            archive_dest = os.path.join(dest,
                                        os.path.relpath(file_path, start=src))
            archive.write(file_path, archive_dest)


def zip_file(archive, src_file, dest_dir=""):
    """Add a file to a ZIP file.

    Adds src_file to archive in the directory dest_dir, relative to the root of
    the archive.

    Args:
       archive: A ZipFile opened for append or write.
       src_file: Source file to add to the archive.
       dest_dir: Relative destination path in the archive for this file.
    """
    archive.write(src_file, os.path.join(dest_dir, os.path.basename(src_file)))


def archive_symbols(args, project):
    """Archive symbol files for the kernel and each trusted app"""
    mkdir(args.archive)

    proj_buildroot = os.path.join(args.build_root, "build-" + project)
    filename = os.path.join(args.archive, f"{project}-{args.buildid}.syms.zip")

    with ZipFile(filename, 'a', compression=ZIP_DEFLATED) as archive:
        print("Archiving symbols in " + os.path.relpath(filename, args.archive))

        # archive the kernel elf file
        zip_file(archive, os.path.join(proj_buildroot, "lk.elf"))

        # archive the kernel symbols
        zip_file(archive, os.path.join(proj_buildroot, "lk.elf.sym"))
        zip_file(archive, os.path.join(proj_buildroot, "lk.elf.sym.sorted"))

        # archive path/to/app.syms.elf for each trusted app
        zip_dir(archive, proj_buildroot, "", lambda f: f.endswith("syms.elf"))


def archive(build_config, args):
    # Copy the files we care about to the archive directory
    for project in args.project:
        # config-driven archiving
        for item in build_config.dist:
            archive_build_file(args, project, item.src, item.dest,
                               optional=item.optional)

        # copy out tos.img if it exists
        archive_build_file(args, project, "tos.img", optional=True)

        # copy out monitor if it exists
        archive_build_file(args, project, "monitor/monitor.bin", "monitor.bin",
                           optional=True)

        # copy out trusty.padded if it exists
        archive_build_file(args, project, "trusty.padded", optional=True)

        # copy out trusty.signed if it exists
        archive_build_file(args, project, "trusty.signed", optional=True)

        # copy out trusty_usb.signed if it exists
        archive_build_file(args, project, "trusty_usb.signed", optional=True)

        # copy out lk image
        archive_build_file(args, project, "lk.bin")

        # copy out qemu package if it exists
        archive_build_file(args, project, "trusty_qemu_package.zip", optional=True)

        # copy out test package if it exists
        archive_build_file(args, project, "trusty_test_package.zip", optional=True)

        # export the app package tool for use in the SDK. This can go away once
        # all the SDK patches have landed, as the tool will be packaged in the
        # SDK zip.
        archive_build_file(args, project, "host_tools/apploader_package_tool",
                           "apploader_package_tool", optional=True)

        # copy out symbol files for kernel and apps
        archive_symbols(args, project)


def get_build_deps(project_name, project, project_names, already_built):
    if project_name not in already_built:
        already_built.add(project_name)
        for dep_project_name, dep_project in project.also_build.items():
            get_build_deps(dep_project_name, dep_project, project_names,
                           already_built)
        project_names.append(project_name)


def main(default_config=None):
    top = os.path.abspath(os.path.join(script_dir, "../../../../.."))
    os.chdir(top)

    parser = argparse.ArgumentParser()

    parser.add_argument("project", type=str, nargs="*", default=[".test.all"],
                        help="Project to build and/or test.")
    parser.add_argument("--build-root", type=str,
                        default=os.path.join(top, "build-root"),
                        help="Root of intermediate build directory.")
    parser.add_argument("--archive", type=str, default=None,
                        help="Location of build results directory.")
    parser.add_argument("--buildid", type=str, help="Server build id")
    parser.add_argument("--jobs", type=str, default=multiprocessing.cpu_count(),
                        help="Max number of build jobs.")
    parser.add_argument("--test", type=str, action="append",
                        help="Manually specify test(s) to run. "
                        "Only build projects that have test(s) enabled that "
                        "matches a listed regex.")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose debug output from test(s).")
    parser.add_argument("--debug-on-error", action="store_true",
                        help="Wait for debugger connection if test fails.")
    parser.add_argument("--clang", action="store_true", default=None,
                        help="Build with clang.")
    parser.add_argument("--skip-build", action="store_true", help="Skip build.")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip running tests.")
    parser.add_argument("--run-disabled-tests", action="store_true",
                        help="Also run disabled tests.")
    parser.add_argument("--skip-project", action="append", default=[],
                        help="Remove project from projects being built.")
    parser.add_argument("--config", type=str, help="Path to an alternate "
                        "build-config file.", default=default_config)
    parser.add_argument("--android", type=str,
                        help="Path to an Android build to run tests against.")
    parser.add_argument("--sdk", action="store_true", help="Build SDK for all "
                        "specified projects.")
    args = parser.parse_args()

    if args.archive is None:
        args.archive = os.path.join(args.build_root, "archive")

    build_config = trusty_build_config.TrustyBuildConfig(
        config_file=args.config, android=args.android)

    projects = []
    for project in args.project:
        if project == ".test.all":
            projects += build_config.get_projects(build=True)
        elif project == ".test":
            projects += build_config.get_projects(build=True, have_tests=True)
        else:
            projects.append(project)

    # skip specific projects
    ok = True
    for skip in args.skip_project:
        if skip in projects:
            projects.remove(skip)
        else:
            sys.stderr.write(
                "ERROR unknown project --skip-project={}\n".format(skip))
            ok = False
    if not ok:
        sys.exit(1)

    if args.test:
        args.test = [re.compile(testpattern) for testpattern in args.test]

        def has_test(proj_name):
            """filter function to check if a project has args.test."""
            proj = build_config.get_project(proj_name)
            for test in proj.tests:
                if not test.enabled and not args.run_disabled_tests:
                    continue
                if run_tests.test_should_run(test.name, args.test):
                    return True
            return False
        projects = filter(has_test, projects)

    # find build dependencies
    projects_old = projects
    projects = []
    built_projects = set()
    for project_name in projects_old:
        get_build_deps(project_name,
                       build_config.get_project(project_name),
                       projects,
                       built_projects)
    args.project = projects

    print("Projects", str(projects))

    if args.skip_build:
        print("Skip build for", args.project)
    else:
        build(args)
        archive(build_config, args)

    if args.sdk:
        assemble_sdk(args)

    # Run tests
    if not args.skip_tests:
        test_failed = []
        test_results = []
        tests_passed = 0
        tests_failed = 0
        projects_passed = 0
        projects_failed = 0

        for project in projects:
            test_result = run_tests.run_tests(build_config, args.build_root,
                                              project, run_disabled_tests=
                                              args.run_disabled_tests,
                                              test_filter=args.test,
                                              verbose=args.verbose,
                                              debug_on_error=
                                              args.debug_on_error)
            if not test_result.passed:
                test_failed.append(project)
            if test_result.passed_count:
                projects_passed += 1
                tests_passed += test_result.passed_count
            if test_result.failed_count:
                projects_failed += 1
                tests_failed += test_result.failed_count
            test_results.append(test_result)

        for test_result in test_results:
            test_result.print_results()

        sys.stdout.write("\n")
        if projects_passed:
            sys.stdout.write("[  PASSED  ] {} tests in {} projects.\n".format(
                tests_passed, projects_passed))
        if projects_failed:
            sys.stdout.write("[  FAILED  ] {} tests in {} projects.\n".format(
                tests_failed, projects_failed))
            sys.stdout.flush()

            # Print the failed tests again to stderr as the build server will
            # store this in a separate file with a direct link from the build
            # status page. The full build long page on the build server, buffers
            # stdout and stderr and interleaves them at random. By printing
            # the summary to both stderr and stdout, we get at least one of them
            # at the bottom of that file.
            for test_result in test_results:
                test_result.print_results(print_failed_only=True)
            sys.stderr.write("[  FAILED  ] {} tests in {} projects.\n".format(
                tests_failed, projects_failed))

        if test_failed:
            sys.exit(1)


if __name__ == "__main__":
    main()
