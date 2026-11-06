"""HTTP plumbing shared by the real providers (standard library only).

* Every redirect is refused. urllib would otherwise send the credential header on to the redirect target,
  so a hostile or misconfigured endpoint could collect the key.
* Replies are read up to ``MAX_RESPONSE_BYTES`` + 1, so an oversized reply is detected without reading it all.
"""

import urllib.request

MAX_RESPONSE_BYTES = 1_048_576


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would forward the credential header to a redirect target; refuse every redirect instead."""

    def redirect_request(self, *_args, **_kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)  # keeps the default proxy and TLS handling
