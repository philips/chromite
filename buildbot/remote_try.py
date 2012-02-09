#!/usr/bin/python

# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import constants
import datetime
import getpass
import os
import shutil
import sys
import tempfile

if __name__ == '__main__':
  sys.path.insert(0, constants.SOURCE_ROOT)

from chromite.buildbot import repository
from chromite.buildbot import manifest_version
from chromite.lib import cros_build_lib as cros_lib

class RemoteTryJob(object):
  """Remote Tryjob that is submitted through a Git repo."""
  SSH_URL = os.path.join(constants.GERRIT_SSH_URL,
                         'chromiumos/tryjobs')

  def __init__(self, options, bots):
    """Construct the object.

    Args:
      options: The parsed options passed into cbuildbot.
      bots: A list of configs to run tryjobs for.
    """
    values = {}
    self.user = values['user'] = getpass.getuser()
    cwd = os.path.dirname(os.path.realpath(__file__))
    values['email'] = cros_lib.GetProjectUserEmail(cwd)
    # Name of the job that appears on the waterfall.
    values['name'] = ','.join(options.gerrit_patches)
    values['issue'] = ' '.join(options.gerrit_patches)
    values['bot'] = ','.join(bots)
    self.description = '\n'.join(
        '%s=%s' % (k, v) for (k, v) in sorted(values.iteritems()))
    self.buildroot = options.buildroot
    self.tryjob_repo = None

  def _Submit(self, dryrun):
    """Internal submission function.  See Submit() for arg description."""
    # TODO(rcui): convert to shallow clone when that's available.
    repository.CloneGitRepo(self.tryjob_repo, self.SSH_URL)
    manifest_version.PrepForChanges(self.tryjob_repo, False)

    current_time = datetime.datetime.utcnow()
    file_name = '%s.%s' % (self.user,
                           current_time.strftime("%Y.%m.%d_%H.%M.%S"))
    fullpath = os.path.join(self.tryjob_repo, file_name)
    # Both commit description and contents of file contain tryjob specs.
    with open(fullpath, 'w+') as job_desc_file:
      job_desc_file.write(self.description)

    cros_lib.RunCommand(['git', 'add', file_name], cwd=self.tryjob_repo)
    cros_lib.RunCommand(['git', 'commit', '-m', self.description],
                        cwd=self.tryjob_repo)

    try:
      cros_lib.GitPushWithRetry(manifest_version.PUSH_BRANCH, self.tryjob_repo,
                                dryrun=dryrun)
    except cros_lib.GitPushFailed:
      cros_lib.Error('Failed to submit tryjob.  This could be due to too many '
                     'submission requests by users.  Please try again.')
      raise

  def Submit(self, workdir=None, dryrun=False):
    """Submit the tryjob through Git.

    Args:
      workdir: The directory to clone tryjob repo into.  If you pass this
               in, you are responsible for deleting the directory.  Used for
               testing.
      dryrun: Setting to true will run everything except the final submit step.
    """
    self.tryjob_repo = workdir
    if self.tryjob_repo is None:
      self.tryjob_repo = tempfile.mkdtemp()

    try:
      self._Submit(dryrun)
    finally:
      if workdir is None:
        shutil.rmtree(self.tryjob_repo)