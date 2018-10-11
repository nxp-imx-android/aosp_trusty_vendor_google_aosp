#!/usr/bin/env python2.7
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
import multiprocessing
import os
import shutil
import subprocess
import sys

import run_tests
import trusty_build_config

script_dir = os.path.dirname(os.path.abspath(__file__))


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
        return os.getlogin() + "@" + os.uname()[1] + "-" + str(num)


def mkdir(path):
    """Create directory includig parents if it does not already exist."""
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
    print "Copy:", repr(src), "->", repr(dest)
    shutil.copy(src, dest)


def archive_build_file(args, project, src, dest=None, optional=False):
    """Copy a file to build archive directory.

    Construct src and dest path and call copy_file.

    Args:
       args: Program arguments.
       project: Project name.
       src: Source path relative to project build dir.
       dest: Optional dest path relative to archive dir. Can be ommitted if src
           is a simple filename.
       optional: Optional boolean argument. If True don't exit if source file
           does not exist.
    """
    if not dest:
        dest = src
    src = os.path.join(args.build_root, "build-" + project, src)
    dest = os.path.join(args.archive, project + "-" + args.buildid + "." + dest)
    copy_file(src, dest, optional=optional)


def build(args):
    """Call build system and copy build files to archive dir."""
    mkdir(args.build_root)
    mkdir(args.archive)

    if args.buildid is None:
        args.buildid = get_new_build_id(args.build_root)
    print "BuildID", args.buildid

    # build projects
    failed = []

    for project in args.project:
        cmd = "source " + os.path.join(script_dir, "envsetup.sh")
        cmd += "; export BUILDROOT=" + args.build_root
        cmd += "; export BUILDID=" + args.buildid
        cmd += "; nice make " + project + " -j " + str(args.jobs)
        status = subprocess.call(cmd, shell=True, executable="/bin/bash")
        print "cmd: '" + cmd + "' returned", status
        if status:
            failed.append(project)

    if failed:
        print
        print "some projects have failed to build:"
        print str(failed)
        exit(1)

    # Copy the files we care about to the archive directory
    for project in args.project:
        # copy out tos.img if it exists
        archive_build_file(args, project, "tos.img", optional=True)

        # copy out monitor if it exists
        archive_build_file(args, project, "monitor/monitor.bin", "monitor.bin",
                           optional=True)

        # copy out lk image
        archive_build_file(args, project, "lk.bin")

        # collect and save all .lst
        subprocess.call("cd " +
                        os.path.join(args.build_root, "build-" + project) +
                        ';find . -name "*.lst" -print ' +
                        "| zip " + os.path.join(args.archive, project + "-" +
                                                args.buildid + ".lst.zip") +
                        " -@", shell=True, executable="/bin/bash")


def main():
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
                        "Only build projects that have listed test(s) enabled.")
    parser.add_argument("--skip-build", action="store_true", help="Skip build.")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip running tests.")
    args = parser.parse_args()

    if args.archive is None:
        args.archive = os.path.join(args.build_root, "archive")

    build_config = trusty_build_config.TrustyBuildConfig()

    projects = []
    for project in args.project:
        if project == ".test.all":
            projects += build_config.get_projects(build=True)
        elif project == ".test":
            projects += build_config.get_projects(build=True, have_tests=True)
        else:
            projects.append(project)

    if args.test:
        def has_test(project_name):
            """filter function to check if a project has args.test."""
            project = build_config.get_project(project_name)
            return not set(args.test).isdisjoint(project.host_tests +
                                                 project.unit_tests)
        projects = filter(has_test, projects)
    args.project = projects
    print "Projects", str(projects)

    if args.skip_build:
        print "Skip build for", args.project
    else:
        build(args)

    # Run tests
    if not args.skip_tests:
        test_failed = []
        test_results = []

        for project in projects:
            test_result = run_tests.run_tests(build_config, args.build_root,
                                              project, test_filter=args.test)
            if not test_result.passed:
                test_failed.append(project)
            test_results.append(test_result)

        for test_result in test_results:
            test_result.print_results()

        if test_failed:
            sys.stdout.flush()
            sys.stderr.write("\n")
            sys.stderr.write(str(len(test_failed)) +
                             " projects have failed tests:\n")
            sys.stderr.write(str(test_failed) + "\n")
            exit(1)


if __name__ == "__main__":
    main()
