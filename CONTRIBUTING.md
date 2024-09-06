## Contributor's Guide

### Where the Code Lives

The upstream git repo is on [GitHub](https://github.com/storaged-project/blivet).

### Branching Model

`main` is the only "active development" branch, new features should go to this branch. Topic branches may exist for older releases for bug fixing purposes, for example `3.10-branch` for the 3.10.X releases.

`rhelX-branch` branches are used for backporting and testing changes for RHEL releases, but the RHEL development itself happens on the [CentOS Stream GitLab repository](https://gitlab.com/redhat/centos-stream/rpms/python-blivet/). In general changes for RHEL should go to the `main` branch first and will be then backported to the appropriate RHEL branches manually.

Note that before the 3.11 release cycle the branching model used to be different with separate branches for development and releases, see the `CONTRIBUTING` file on the `3.10-devel` branch for more details.

### Guidelines for Commits

Please make sure `make ci` passes with your patches applied before opening a pull request.

#### Commit Messages

The first line should be a succinct description of what the commit does. If your commit is fixing a bug in Red Hat's bugzilla instance, you should add `` (#123456)`` to the end of the first line of the commit message. The next line should be blank, followed (optionally) by a more in-depth description of your changes. Here's an example:

    Wait for auto-activation of LVs when lvmetad is running. (#1261621)

    When lvmetad is running, activating the last PV in a VG will trigger
    automatic activation of the LVs. This happens asynchronously, however,
    so we have to just wait for it to be done. Since it is possible to
    configure which VGs/LVs get auto-activated, we only wait for 30
    seconds. After that, we will try to activate the LV ourselves.

#### Creating a Pull Request

When creating a pull request for blivet you have to give some thought to what branch to base your pull request on. New features should go to the default `main` branch. For bugfixes you should choose the branch corresponding to the oldest `x.y` release that should include your fix and open separate pull requests for all branches from this release to the latest release and for the `main` branch as well.

Note that there is a minimum review period of 24 hours for any patch. The purpose of this rule is to ensure that all interested parties have an opportunity to review every patch. When posting a patch before or after a holiday break it is important to extend this period as appropriate.

Note that all CI checks are expected to pass for the pull request to be merged. Ask the maintainers if you cannot reproduce a CI failure locally or if you suspect the failed test run is caused by the CI infrastructure issue.

## Release & Build Procedures

### Upstream Release Procedure

#### Update the Release Notes
Scan through the changes in the new release and add any that seem relevant to `release_notes.rst` using that file's existing structure from previous releases. You will commit the release notes changes along with the other release artifacts in the next step.

#### Make the Release
To bump the version, update it in all of the necessary places, and generate the changelog for the rpm spec file, run `make bumpver`. Take a look at the changes using `git diff` to make sure it all looks correct. Then commit the new version using `git commit -a -m "New version: <version>"` (eg: `git commit -a -m "New version: 3.2.0"`).

Next, tag the new release with the command `make release`. This will prompt you for a GPG key passphrase in generating a signed tag, and will generate a tar archive containing the new release along with current translations. (NOTE: The upstream release on github does not contain the translations.)

Push the new release and tags to the upstream remote (`git push && git push --tags`).

#### Publishing the Release on GitHub
After pushing the tags to GitHub go to the [Releases](https://github.com/storaged-project/blivet/releases) page and create a new release from the pushed tag by selecting the appropriate tag (eg: `blivet-3.2.2`) and selecting *Edit tag* in the UI. Change the release title to something like `blivet 3.2.2`, fill in the description and attach source tarballs generated with `make release`.

#### Updating documentation
Generate documentation for the new release
```
make -C doc html
```
Copy the documentation from `doc/_build/html` to a temporary directory, switch to the `gh-pages`, copy the documentation back and commit and push the changes.

### Fedora Build Procedure

Fedora builds are automated using Packit. After tagging a new release Packit will open PRs against all supported versions of Fedora in Pagure. Fedora maintainer will review and merge those PRs, afterwards, Packit will do the builds and Bodhi updates as well.

## PyPI Build Procedure
Prepare archive for PyPI: `python3 setup.py sdist bdist_wheel`

Check the archive: `twine check dist/*`

Upload to Test PyPI (optional): `twine upload --repository-url https://test.pypi.org/legacy/ dist/*`

Upload to PyPI: `twine upload dist/*`
