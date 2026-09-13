# Punctuation survives in generated slugs

Python 3.11. A blog title is converted into a URL component using `slugify`.

Input: `Hello,   World!`

Expected: `hello-world`

Observed: `hello,---world!`

The slug should keep ASCII letters and digits, lowercase letters, remove other
punctuation, collapse runs of whitespace to a single hyphen, and trim leading or
trailing whitespace. An empty title should produce an empty slug.

Please reproduce the bug and propose a regression test. Do not publish anything.
