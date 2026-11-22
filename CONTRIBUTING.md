# Contributing

> ภาษาไทย: โปรเจกต์นี้เป็นต้นแบบที่ดูแลโดยคนคนเดียว ถามหรือแจ้งปัญหาได้ทาง issue ใช้ข้อมูลสมมติเท่านั้น
> ห้ามวางข้อมูลส่วนบุคคลจริงหรือคีย์ลับ และถ้าพบช่องโหว่ให้แจ้งแบบส่วนตัวตาม [SECURITY.md](SECURITY.md)

Thank you for your interest. System Neuron Flow AI is an early prototype kept by one person. The code and docs
are written with AI coding agents under the owner's direction, and the owner decides what is merged. There is
no promised response time.

## Questions, bugs and ideas

- Open an issue and choose a template. For anything larger than a typo, open an issue before a pull request,
  so we can agree on the change first.
- Security problems: never in a public issue. Report them privately, as [SECURITY.md](SECURITY.md) describes.

## Rules every change keeps

The full list is in [CLAUDE.md](CLAUDE.md#3-rules-you-must-not-break). The ones that matter most:

- **Synthetic data only.** Never put real personal data, real case text or a key in an issue, a commit, a test
  or a log. Open datasets count only under ADR-024 ([architecture.md](docs/architecture.md)).
- **Core stays unchanged.** `neuron_flow/` changes only with a new ADR first, and it never imports `app.*`.
- **AI proposes, code validates, people decide.** Nothing is decided or sent automatically.
- **Standard library first.** A new dependency needs a reason in the pull request.

## Pull requests

1. Branch from `main` and keep one topic per pull request, with an English title.
2. Commit with GitHub's noreply address. The *Secret scan* workflow's `commit-emails` job fails a pull
   request whose commits carry a personal e-mail address.
3. Add tests for the new behaviour, including failure paths, and run the suite:

   ```bash
   python -m unittest discover -s tests -v
   ```

   CI runs it on Python 3.10 and 3.12, with the eval and robustness gates
   ([CLAUDE.md, "Checking your work"](CLAUDE.md#4-checking-your-work)).
4. Update the docs in the same pull request and fill in the template
   ([definition of done](CLAUDE.md#5-definition-of-done-for-a-pr)).

## Conduct and license

Everyone who takes part follows the [code of conduct](CODE_OF_CONDUCT.md). By submitting a contribution you
agree that it is licensed under the project's license, [GPL-3.0-only](LICENSE).
