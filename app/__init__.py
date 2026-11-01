"""Application-level extensions around the portable core."""

import logging

# Service log lines go to whatever the running program configures (app.serve sends them to stdout).
# Without configuration, for example inside tests, they stay quiet.
logging.getLogger("neuron_flow").addHandler(logging.NullHandler())
