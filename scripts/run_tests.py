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
#
# This test script to be used by the build server.
# It is supposed to be executed from trusty root directory
# and expects the following environment variables:
#
"""Run tests for a project."""

import argparse
import subprocess
import sys

import trusty_build_config


class TestResults(object):
    """Stores test results.

    Attributes:
        project: Name of project that tests were run on.
        passed: True if all tests passed, False if one or more tests failed.
        tests: List of tuples storing test name an status.
    """

    def __init__(self, project):
        """Inits TestResults with project name and empty test results."""
        self.project = project
        self.passed = True
        self.test_results = []

    def add_result(self, test, passed):
        """Add a test result."""
        self.test_results.append((test, passed))
        if not passed:
            self.passed = False

    def print_results(self):
        """Print test results."""
        print "Project:", self.project, "PASSED" if self.passed else "FAILED"
        if not self.test_results:
           print "  No tests"
        for test, passed in self.test_results:
           print "  " + test, "PASSED" if passed else "FAILED"


def run_tests(build_config, root, project, test_filter=None):
    """Run tests for a project.

    Args:
        build_config: TrustyBuildConfig object.
        root: Trusty build root output directory.
        project: Project name.
        test_filter: Optional list that limits the tests to run.

    Returns:
        TestResults object listing overall and detailed test results.
    """
    tests = build_config.get_project(project=project)

    test_results = TestResults(project)
    test_failed = []
    test_passed = []

    def run_test(name, cmd):
        print "Running", name, "on", project
        print "Command line:", " ".join([s.replace(" ", "\\ ") for s in cmd])
        sys.stdout.flush()
        status = subprocess.call(cmd)
        print name, "returned", status
        test_results.add_result(name, status == 0)
        (test_failed if status else test_passed).append(name)

    for host_test in tests.host_tests:
        if test_filter and host_test not in test_filter:
            continue
        run_test(name="host-test:" + host_test,
                 cmd=["nice",
                      root + "/build-" + project + "/host_tests/" +
                      host_test])

    for unit_test in tests.unit_tests:
        if test_filter and unit_test not in test_filter:
            continue
        run_test(name="unit-test:" + unit_test,
                 cmd=["nice",
                      root + "/build-" + project + "/run-qemu",
                      "-semihosting-config", "arg=boottest " + unit_test,
                      "-serial", "null",
                      "-serial", "mon:stdio"])

    if test_passed:
        print len(test_passed), "tests passed for project", project + ":"
        print test_passed
    elif not test_failed:
        print "No tests ran for project", project
    if test_failed:
        sys.stdout.flush()
        sys.stderr.write("\n")
        sys.stderr.write(str(len(test_failed)) +
                         " tests have failed for project " + project + ":\n")
        sys.stderr.write(str(test_failed) + "\n")

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
        exit(1)


if __name__ == "__main__":
    main()
