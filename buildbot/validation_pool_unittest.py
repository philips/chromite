#!/usr/bin/python

# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module that contains unittests for validation_pool module."""

import mox
import StringIO
import sys
import unittest
import urllib

import constants
sys.path.append(constants.SOURCE_ROOT)

from chromite.buildbot import gerrit_helper
from chromite.buildbot import patch as cros_patch
from chromite.buildbot import validation_pool


class TestValidationPool(mox.MoxTestBase):
  """Tests methods in validation_pool.ValidationPool."""

  def _TreeStatusFile(self, message, general_state):
    """Returns a file-like object with the status message writtin in it."""
    my_response = self.mox.CreateMockAnything()
    my_response.json = '{"message": "%s", "general_state": "%s"}' % (
        message, general_state)
    return my_response

  def _TreeStatusTestHelper(self, tree_status, general_state, expected_return,
                            retries_500=0):
    """Tests whether we return the correct value based on tree_status."""
    return_status = self._TreeStatusFile(tree_status, general_state)
    self.mox.StubOutWithMock(urllib, 'urlopen')
    status_url = 'https://chromiumos-status.appspot.com/current?format=json'
    for _ in range(retries_500):
      urllib.urlopen(status_url).AndReturn(return_status)
      return_status.getcode().AndReturn(500)

    urllib.urlopen(status_url).AndReturn(return_status)
    return_status.getcode().AndReturn(200)
    return_status.read().AndReturn(return_status.json)
    self.mox.ReplayAll()
    self.assertEqual(validation_pool.ValidationPool._IsTreeOpen(),
                     expected_return)
    self.mox.VerifyAll()

  def testTreeIsOpen(self):
    """Tests that we return True is the tree is open."""
    self._TreeStatusTestHelper('Tree is open (flaky bug on flaky builder)',
                               'open', True)

  def testTreeIsClosed(self):
    """Tests that we return false is the tree is closed."""
    self._TreeStatusTestHelper('Tree is closed (working on a patch)', 'closed',
                               False)

  def testTreeIsThrottled(self):
    """Tests that we return false is the tree is throttled."""
    self._TreeStatusTestHelper('Tree is throttled (waiting to cycle)',
                               'throttled', True)

  def testTreeStatusWithNetworkFailures(self):
    """Checks for non-500 errors.."""
    self._TreeStatusTestHelper('Tree is open (flaky bug on flaky builder)',
                               'open', True, retries_500=2)

  def testSimpleDepApplyPoolIntoRepo(self):
    """Test that can apply changes correctly and respect deps.

    This tests a simple out-of-order change where change1 depends on change2
    but tries to get applied before change2.  What should happen is that
    we should notice change2 is a dep of change1 and apply it first.
    """
    patch1 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch2 = self.mox.CreateMock(cros_patch.GerritPatch)

    patch1.revision = 'ChangeId1'
    patch2.revision = 'ChangeId2'
    patch1.url = 'fake_url/1'
    patch2.url = 'fake_url/2'
    build_root = 'fakebuildroot'

    pool = validation_pool.ValidationPool(False, 1, False)
    pool.changes = [patch1, patch2]

    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'GerritDependencies')
    patch1.GerritDependencies(build_root).AndReturn(['ChangeId2'])

    patch2.Apply(build_root, trivial=True)
    patch1.Apply(build_root, trivial=True)

    self.mox.ReplayAll()
    self.assertTrue(pool.ApplyPoolIntoRepo(build_root))
    self.mox.VerifyAll()

  def testSimpleDepApplyPoolIntoRepo(self):
    """Test that we don't try to apply a change without met dependencies.

    Patch2 is in the validation pool that depends on Patch1 (which is not)
    Nothing should get applied.
    """
    patch1 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch2 = self.mox.CreateMock(cros_patch.GerritPatch)

    patch1.revision = 'ChangeId1'
    patch2.revision = 'ChangeId2'
    patch2.project = 'fake_project'
    patch1.url = 'fake_url/1'
    patch2.url = 'fake_url/2'
    build_root = 'fakebuildroot'

    pool = validation_pool.ValidationPool(False, 1, False)
    pool.changes = [patch2]
    helper = self.mox.CreateMock(gerrit_helper.GerritHelper)
    pool.gerrit_helper = helper
    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'GerritDependencies')
    patch2.GerritDependencies(build_root).AndReturn(['ChangeId1'])
    helper.IsRevisionCommitted(patch2.project, patch1.revision).AndReturn(False)

    self.mox.ReplayAll()
    self.assertFalse(pool.ApplyPoolIntoRepo(build_root))
    self.mox.VerifyAll()

  def testSimpleDepApplyWhenAlreadySubmitted(self):
    """Test that we apply a change with dependency already committed."""
    patch1 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch2 = self.mox.CreateMock(cros_patch.GerritPatch)

    patch1.revision = 'ChangeId1'
    patch2.revision = 'ChangeId2'
    patch2.project = 'fake_project'
    patch1.url = 'fake_url/1'
    patch2.url = 'fake_url/2'
    build_root = 'fakebuildroot'

    pool = validation_pool.ValidationPool(False, 1, False)
    pool.changes = [patch2]
    helper = self.mox.CreateMock(gerrit_helper.GerritHelper)
    pool.gerrit_helper = helper
    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'GerritDependencies')
    patch2.GerritDependencies(build_root).AndReturn(['ChangeId1'])
    helper.IsRevisionCommitted(patch2.project, patch1.revision).AndReturn(True)
    patch2.Apply(build_root, trivial=True)

    self.mox.ReplayAll()
    self.assertTrue(pool.ApplyPoolIntoRepo(build_root))
    self.mox.VerifyAll()

  def testSimpleDepFailedApplyPoolIntoRepo(self):
    """Test that can apply changes correctly when one change fails to apply.

    This tests a simple change order where 1 depends on 2 and 1 fails to apply.
    Only 1 should get tried as 2 will abort once it sees that 1 can't be
    applied.  3 with no dependencies should go through fine.

    Since patch1 fails to apply, we should also get a call to handle the
    failure.
    """
    patch1 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch2 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch3 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch4 = self.mox.CreateMock(cros_patch.GerritPatch)

    patch1.revision = 'ChangeId1'
    patch2.revision = 'ChangeId2'
    patch3.revision = 'ChangeId3'
    patch4.revision = 'ChangeId4'
    patch1.url = 'fake_url/1'
    patch2.url = 'fake_url/2'
    patch3.url = 'fake_url/3'
    patch4.url = 'fake_url/4'
    build_root = 'fakebuildroot'

    pool = validation_pool.ValidationPool(False, 1, False)
    pool.changes = [patch1, patch2, patch3, patch4]
    pool.build_log = 'log'

    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'GerritDependencies')
    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'HandleCouldNotApply')
    patch1.GerritDependencies(build_root).AndReturn([])
    patch1.Apply(build_root, trivial=True).AndRaise(
        cros_patch.ApplyPatchException(patch1))

    patch2.GerritDependencies(build_root).AndReturn(['ChangeId1'])
    patch3.GerritDependencies(build_root).AndReturn([])
    patch3.Apply(build_root, trivial=True)

    # This one should be handled later (not where patch1 is handled.
    patch4.GerritDependencies(build_root).AndReturn([])
    patch4.Apply(build_root, trivial=True).AndRaise(
        cros_patch.ApplyPatchException(
            patch1,
            type=cros_patch.ApplyPatchException.TYPE_REBASE_TO_PATCH_INFLIGHT))

    patch1.HandleCouldNotApply(None, pool.build_log, dryrun=False)

    self.mox.ReplayAll()
    self.assertTrue(pool.ApplyPoolIntoRepo(build_root))
    self.assertTrue(patch4 in pool.changes_that_failed_to_apply_earlier)
    self.mox.VerifyAll()

  def testMoreComplexDepApplyPoolIntoRepo(self):
    """More complex deps test.

    This tests a total of 2 change chains where the first change we see
    only has a partial chain with the 3rd change having the whole chain i.e.
    1->2, 3->1->2, 4->nothing.  Since we get these in the order 1,2,3,4 the
    order we should apply is 2,1,3,4.
    """
    patch1 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch2 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch3 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch4 = self.mox.CreateMock(cros_patch.GerritPatch)

    patch1.revision = 'ChangeId1'
    patch2.revision = 'ChangeId2'
    patch3.revision = 'ChangeId3'
    patch4.revision = 'ChangeId4'
    patch1.url = 'fake_url/1'
    patch2.url = 'fake_url/2'
    patch3.url = 'fake_url/3'
    patch4.url = 'fake_url/4'
    build_root = 'fakebuildroot'

    pool = validation_pool.ValidationPool(False, 1, False)
    pool.changes = [patch1, patch2, patch3, patch4]

    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'GerritDependencies')
    patch1.GerritDependencies(build_root).AndReturn(['ChangeId2'])
    patch3.GerritDependencies(build_root).AndReturn(['ChangeId1', 'ChangeId2'])
    patch4.GerritDependencies(build_root).AndReturn([])

    patch2.Apply(build_root, trivial=True)
    patch1.Apply(build_root, trivial=True)
    patch3.Apply(build_root, trivial=True)
    patch4.Apply(build_root, trivial=True)

    self.mox.ReplayAll()
    self.assertTrue(pool.ApplyPoolIntoRepo(build_root))
    self.mox.VerifyAll()

  def testNoDepsApplyPoolIntoRepo(self):
    """Simple apply of two changes with no dependent CL's."""
    patch1 = self.mox.CreateMock(cros_patch.GerritPatch)
    patch2 = self.mox.CreateMock(cros_patch.GerritPatch)

    patch1.revision = 'ChangeId1'
    patch2.revision = 'ChangeId2'
    patch1.url = 'fake_url/1'
    patch2.url = 'fake_url/2'
    build_root = 'fakebuildroot'

    pool = validation_pool.ValidationPool(False, 1, False)
    pool.changes = [patch1, patch2]

    self.mox.StubOutWithMock(cros_patch.GerritPatch, 'GerritDependencies')
    patch1.GerritDependencies(build_root).AndReturn([])
    patch2.GerritDependencies(build_root).AndReturn([])

    patch1.Apply(build_root, trivial=True)
    patch2.Apply(build_root, trivial=True)

    self.mox.ReplayAll()
    self.assertTrue(pool.ApplyPoolIntoRepo(build_root))
    self.mox.VerifyAll()


if __name__ == '__main__':
  unittest.main()