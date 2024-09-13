# Contributing to nilrt-snac

Thanks for taking an interest in contributing to [NILRT](https://github.com/ni/nilrt)'s SNAC configuration tool!

This document should provide useful information for how to get started developing, testing, and upstreaming to our mainline.


## Communications

Clone the **source** from NI's canonical upstream [GitHub](https://github.com/ni/nilrt-snac/) repo, and read the [README](https://github.com/ni/nilrt-snac/blob/master/README.md).

File **bugs** and **enhancement** requests to the canonical repo's [Issues tracker](https://github.com/ni/nilrt-snac/issues).

Send **security** concerns to the NI Security Team, per the [SECURITY.md](https://github.com/ni/nilrt-snac/blob/master/docs/SECURITY.md).


## Building

`nilrt-snac` is implemented in shell scripts that do not require compilation or packaging; it does not require a build step.

See the README for installation instructions.


## Testing

The nilrt-snac project has integration tests implemented in pytest. The integration tests are only valid to run after installing the project to a system. They can be invoked by calling `make installcheck`, or invoking `pytest` against the tests directly.

```bash
make install
make installcheck
```

OR

```bash
python3 -m pytest ${prefix}/lib/nilrt-snac/tests/integration
```

Some test cases are expected to fail, if you install the test to `/usr/local` or on a non-NILRT system.


## Upstreaming Changes

nilrt-snac follows a pull-request model for development.  If you wish to contribute, you will need to create a GitHub account, fork this project, push a branch with your changes to your project, and then submit a pull request.

**Base from master.** This project uses 'master' as its mainline branch ref; please base all pull requests upon that branch.

**Commit Sign-offs Required.** Please remember to sign off your commits (e.g., by using `git commit -s` if you are using the command line client). This amends your git commit message with a line of the form `Signed-off-by: Name Lastname <name.lastname@emailaddress.com>`. Please include all authors of any given commit into the commit message with a `Signed-off-by` line. This indicates that you have read and signed the Developer Certificate of Origin (see below) and are able to legally submit your code to this repository.

See [GitHub's official documentation](https://help.github.com/articles/using-pull-requests/) for more details.


### Developer Certificate of Origin (DCO)

   Developer's Certificate of Origin 1.1

   By making a contribution to this project, I certify that:

   (a) The contribution was created in whole or in part by me and I
       have the right to submit it under the open source license
       indicated in the file; or

   (b) The contribution is based upon previous work that, to the best
       of my knowledge, is covered under an appropriate open source
       license and I have the right under that license to submit that
       work with modifications, whether created in whole or in part
       by me, under the same open source license (unless I am
       permitted to submit under a different license), as indicated
       in the file; or

   (c) The contribution was provided directly to me by some other
       person who certified (a), (b) or (c) and I have not modified
       it.

   (d) I understand and agree that this project and the contribution
       are public and that a record of the contribution (including all
       personal information I submit with it, including my sign-off) is
       maintained indefinitely and may be redistributed consistent with
       this project or the open source license(s) involved.

(taken from [developercertificate.org](https://developercertificate.org/))

See [LICENSE](https://github.com/ni/nilrt-snac/blob/master/LICENSE) for details about how nilrt-snac is licensed.
