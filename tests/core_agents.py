"""Importable toy agents for portable runtime regression tests."""
from neuron_flow.model import TransientAgentError, PermanentAgentError

def echo(message):
    return {"value":message["input"]["value"]}
def validate_echo(message, output):
    if output != {"value":message["input"]["value"]}:
        raise ValueError("Wrong echo result")
def copy_dependency(message):
    return {"copied":message["dependencies"]["first"]["value"]}
def validate_copy(message, output):
    if output != {"copied":message["dependencies"]["first"]["value"]}:
        raise ValueError("Wrong dependency result")
def transient(message):
    if message["attempt"] == 1:
        raise TransientAgentError("Retry required")
    return {"ok":True}
def validate_ok(message, output):
    if output != {"ok":True}: raise ValueError("Bad receipt")
def permanent(message):
    raise PermanentAgentError("Cannot recover this input")
