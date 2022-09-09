#!/bin/sh
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
#
# This test script to be used by the build server.
# It is supposed to be executed from trusty root directory
# and expects the following environment variables:
#
""":" # Shell script (in docstring to appease pylint)
# Find and invoke hermetic python3 interpreter
. "`dirname $0`/envsetup.sh"; exec "$PY3" "$0" "$@"
# Shell script end
Run tests for a project.
"""

import argparse
import importlib
import subprocess
import sys
import time

import trusty_build_config

class TestResults(object):
    """Stores test results.

    Attributes:
        project: Name of project that tests were run on.
        passed: True if all tests passed, False if one or more tests failed.
        passed_count: Number of tests passed.
        failed_count: Number of tests failed.
        test_results: List of tuples storing test name an status.
    """

    def __init__(self, project):
        """Inits TestResults with project name and empty test results."""
        self.project = project
        self.passed = True
        self.passed_count = 0
        self.failed_count = 0
        self.test_results = []

    def add_result(self, test, passed):
        """Add a test result."""
        self.test_results.append((test, passed))
        if passed:
            self.passed_count += 1
        else:
            self.passed = False
            self.failed_count += 1

    def print_results(self, print_failed_only=False):
        """Print test results."""
        if print_failed_only:
            if self.passed:
                return
            sys.stdout.flush()
            out = sys.stderr
        else:
            out = sys.stdout
        test_count = self.passed_count + self.failed_count
        out.write("\n"
                  f"Ran {test_count} tests for project {self.project}.\n")
        if test_count:
            for test, passed in self.test_results:
                if passed:
                    if not print_failed_only:
                        out.write(f"[ {'OK':>8} ] {test}\n")
                else:
                    out.write(f"[ {'FAILED':^8} ] {test}\n")
            out.write(f"[==========] {test_count} tests ran for project "
                      f"{self.project}.\n")
            if self.passed_count and not print_failed_only:
                out.write(f"[  PASSED  ] {self.passed_count} tests.\n")
            if self.failed_count:
                out.write(f"[  FAILED  ] {self.failed_count} tests.\n")


def test_should_run(testname, test_filter):
    """Check if test should run.

    Args:
        testname: Name of test to check.
        test_filter: Regex list that limits the tests to run.

    Returns:
        True if test_filter list is empty or None, True if testname matches any
        regex in test_filter, False otherwise.
    """
    if not test_filter:
        return True
    for r in test_filter:
        if r.search(testname):
            return True
    return False


def run_tests(build_config, root, project, run_disabled_tests=False,
              test_filter=None, verbose=False, debug_on_error=False):
    """Run tests for a project.

    Args:
        build_config: TrustyBuildConfig object.
        root: Trusty build root output directory.
        project: Project name.
        run_disabled_tests: Also run disabled tests from config file.
        test_filter: Optional list that limits the tests to run.
        verbose: Enable debug output.
        debug_on_error: Wait for debugger connection on errors.

    Returns:
        TestResults object listing overall and detailed test results.
    """
    project_config = build_config.get_project(project=project)
    project_root = f"{root}/build-{project}"

    test_results = TestResults(project)

    def load_test_environment():
        sys.path.append(project_root)
        if run := sys.modules.get("run"):
            if not run.__file__.startswith(project_root):
                # run module was imported for another project and needs to be
                # replaced with the one for the current project.
                run = importlib.reload(run)
        else:
            # first import in this interpreter instance, we use importlib rather
            # than a regular import statement since it avoids linter warnings.
            run = importlib.import_module("run")
        sys.path.pop()

        return run

    def run_test(test):
        """Execute a single test and print out helpful information"""
        cmd = test.command[1:]
        disable_rpmb = True if "--disable_rpmb" in cmd else None

        print()
        print("Running", test.name, "on", test_results.project)
        test_start_time = time.time()

        match test:
            case trusty_build_config.TrustyHostTest():
                # append nice and expand path to command
                cmd = ["nice", f"{project_root}/{test.command[0]}"] + cmd
                print("Command line:",
                      " ".join([s.replace(" ", "\\ ") for s in cmd]),
                      flush=True)
                status = subprocess.call(cmd)
            case trusty_build_config.TrustyTest():
                if hasattr(test, "shell_command"):
                    print("Command line:",
                          test.shell_command.replace(" ", "\\ "),
                          flush=True)

                test_env = None
                test_runner = None
                try:
                    test_env = load_test_environment()
                    test_runner = test_env.init(android=
                                                build_config.android,
                                                disable_rpmb=disable_rpmb,
                                                verbose=verbose,
                                                debug_on_error=
                                                debug_on_error)
                    status = test_env.run_test(test_runner, cmd)
                finally:
                    if test_env:
                        test_env.shutdown(test_runner)
            case trusty_build_config.TrustyRebootCommand():
                # ignore reboot commands since we are not (yet) batching
                # tests such that they can share an emulator instance.
                return
            case _:
                raise NotImplementedError(f"Don't know how to run {test.name}")

        elapsed = time.time() - test_start_time
        print(f"{test.name:s} returned {status:d} after {elapsed:.3f} seconds")
        test_results.add_result(test.name, status == 0)

    for test in project_config.tests:
        if not test.enabled and not run_disabled_tests:
            continue
        if not test_should_run(test.name, test_filter):
            continue

        run_test(test)

    return test_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, required=True,
                        help="Root of intermediate build directory.")
    parser.add_argument("--project", type=str, required=True,
                        help="Project to test.")
    args = parser.parse_args()

    build_config = trusty_build_config.TrustyBuildConfig()
    test_results = run_tests(build_config, args.root, args.project)
    test_results.print_results()
    if not test_results.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
