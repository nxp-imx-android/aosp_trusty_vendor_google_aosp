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
from typing import List, Optional
from collections import namedtuple

from trusty_build_config import TrustyTest, TrustyCompositeTest
from trusty_build_config import TrustyRebootCommand, TrustyHostTest
from trusty_build_config import TrustyAndroidTest, TrustyBuildConfig


TestResult = namedtuple("TestResult", "test passed retried")


class TestResults(object):
    """Stores test results.

    Attributes:
        project: Name of project that tests were run on.
        passed: True if all tests passed, False if one or more tests failed.
        passed_count: Number of tests passed.
        failed_count: Number of tests failed.
        flaked_count: Number of tests that failed then passed on second try.
        retried_count: Number of tests that were given a second try.
        test_results: List of tuples storing test name an status.
    """

    def __init__(self, project):
        """Inits TestResults with project name and empty test results."""
        self.project = project
        self.passed = True
        self.passed_count = 0
        self.failed_count = 0
        self.flaked_count = 0
        self.retried_count = 0
        self.test_results = []

    def add_result(self, test: str, passed: bool, retried: bool):
        """Add a test result."""
        self.test_results.append(TestResult(test, passed, retried))
        if passed:
            self.passed_count += 1
            if retried:
                self.flaked_count += 1
        else:
            self.passed = False
            self.failed_count += 1

        if retried:
            self.retried_count += 1

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
            for result in self.test_results:
                match (result.passed, result.retried, print_failed_only):
                    case (False, _, _):
                        out.write(f"[  FAILED  ] {result.test}\n")
                    case (True, retried, False):
                        out.write(f"[       OK ] {result.test}\n")
                        if retried:
                            out.write(f"WARNING: {result.test} was re-run and "
                                      "passed on second try; it may be flaky\n")

            out.write(f"[==========] {test_count} tests ran for project "
                      f"{self.project}.\n")
            if self.passed_count and not print_failed_only:
                out.write(f"[  PASSED  ] {self.passed_count} tests.\n")
            if self.failed_count:
                out.write(f"[  FAILED  ] {self.failed_count} tests.\n")
            if self.flaked_count > 0:
                out.write(f"WARNING: {self.flaked_count} tests passed when "
                          "re-run which indicates that they may be flaky.\n")
            if self.retried_count == MAX_RETRIES:
                out.write(f"WARNING: hit MAX_RETRIES({MAX_RETRIES}) during "
                          "testing after which point, no tests were retried.\n")


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


# Put a global cap on the number of retries to detect flaky tests such that we
# do not risk increasing the time to try all tests substantially. This should be
# fine since *most* tests are not flaky.
# TODO: would it be better to put a cap on the time spent retrying tests? We may
#       not want to retry long running tests.
MAX_RETRIES = 10


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
    test_env = None
    test_runner = None

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

    def print_test_command(name, cmd: Optional[List[str]] = None):
        print()
        print("Running", name, "on", test_results.project)
        if cmd:
            print("Command line:",
                  " ".join([s.replace(" ", "\\ ") for s in cmd]))
        sys.stdout.flush()

    def run_test(test, parent_test: Optional[TrustyCompositeTest] = None,
                 retry=True) -> int:
        """Execute a single test and print out helpful information"""
        nonlocal test_env, test_runner
        cmd = test.command[1:]
        disable_rpmb = True if "--disable_rpmb" in cmd else None

        test_start_time = time.time()

        match test:
            case TrustyHostTest():
                # append nice and expand path to command
                cmd = ["nice", f"{project_root}/{test.command[0]}"] + cmd
                print_test_command(test.name, cmd)
                status = subprocess.call(cmd)
            case TrustyCompositeTest():
                status = 0
                for subtest in test.sequence:
                    if status := run_test(subtest, test, retry):
                        # fail the composite test with the same status code as
                        # the first failing subtest
                        break

            case TrustyTest():
                if isinstance(test, TrustyAndroidTest):
                    print_test_command(test.name, [test.shell_command])
                else:
                    # port tests are identified by their port name, no command
                    print_test_command(test.name)

                if not test_env:
                    test_env = load_test_environment()
                if not test_runner:
                    test_runner = test_env.init(android=build_config.android,
                                                disable_rpmb=disable_rpmb,
                                                verbose=verbose,
                                                debug_on_error=debug_on_error)
                status = test_env.run_test(test_runner, cmd)
            case TrustyRebootCommand() if parent_test:
                assert isinstance(parent_test, TrustyCompositeTest)
                if test_env:
                    test_env.shutdown(test_runner)
                    test_runner = None
                    print("Shut down test environment on", test_results.project)
                # return early so we do not report the time to reboot or try to
                # add the reboot command to test results.
                return 0
            case TrustyRebootCommand():
                raise RuntimeError(
                    "Reboot may only be used inside compositetest")
            case _:
                raise NotImplementedError(f"Don't know how to run {test.name}")

        elapsed = time.time() - test_start_time
        print(f"{test.name:s} returned {status:d} after {elapsed:.3f} seconds")

        if status and retry and test_results.retried_count < MAX_RETRIES:
            print(f"retrying potentially flaky test {test.name} on",
                  test_results.project)
            # TODO: first retry the test without restarting the test environment
            #       and if that fails, restart and then retry if < MAX_RETRIES.
            if test_env:
                test_env.shutdown(test_runner)
                test_runner = None
            status = run_test(test, parent_test, retry=False)
        else:
            test_results.add_result(test.name, status == 0, not retry)
        return status

    try:
        for test in project_config.tests:
            if not test.enabled and not run_disabled_tests:
                continue
            if not test_should_run(test.name, test_filter):
                continue

            run_test(test)
    finally:
        # finally is used here to make sure that we attempt to shutdown the
        # test environment no matter whether an exception was raised or not
        # and no matter what kind of test caused an exception to be raised.
        if test_env:
            test_env.shutdown(test_runner)
        # any saved exception from the try block will be re-raised here

    return test_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, required=True,
                        help="Root of intermediate build directory.")
    parser.add_argument("--project", type=str, required=True,
                        help="Project to test.")
    args = parser.parse_args()

    build_config = TrustyBuildConfig()
    test_results = run_tests(build_config, args.root, args.project)
    test_results.print_results()
    if not test_results.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
