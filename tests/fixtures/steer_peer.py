"""Pipe peer used by test_steer. Its gate makes turn-completion races deterministic."""
import json
import sys
from pathlib import Path

backend, behavior = sys.argv[1:3]
trace, gate = map(Path, sys.argv[3:])
thread, turn = "native-thread", "native-turn"


def emit(msg):
    print(json.dumps(msg), flush=True)


def reply(result):
    emit({"id": msg["id"], "result": result})


def event(method, params):
    emit({"method": method, "params": params})


def complete():
    event("item/completed", {"threadId": thread, "turnId": turn, "item": {
        "type": "agentMessage", "id": "final", "phase": "final_answer", "text": "  原文\r\n保留分歧。\n"}})
    event("turn/completed", {"threadId": thread, "turn": {"id": turn, "status": "completed"}})


for line in sys.stdin:
    msg = json.loads(line)
    method, p = msg.get("method"), msg.get("params", {})
    with trace.open("a", encoding="utf-8") as log:
        log.write(json.dumps(msg) + "\n")
    if method == "initialize":
        reply({"protocolVersion": 1})
    elif method == "thread/start":
        reply({"thread": {"id": thread, "ephemeral": True}, "cwd": p["cwd"], "approvalPolicy": "never",
               "sandbox": {"type": "readOnly", "networkAccess": False}})
    elif method == "turn/start":
        reply({"turn": {"id": turn}})
        for target, text in [("another-thread", "QUESTION: cross-task"), (thread, "QUESTION: Which unit?")]:
            event("item/completed", {"threadId": target, "turnId": turn, "item": {
                "type": "agentMessage", "id": "question", "phase": "commentary", "text": text}})
        if behavior == "instant":
            complete()
    elif method == "turn/steer":
        assert p["threadId"] == thread and p["expectedTurnId"] == turn
        if behavior == "disconnect":
            sys.exit(0)
        if behavior in ("late-ack", "lost-final-ack"):
            complete()
            if behavior == "lost-final-ack":
                sys.exit(0)
            reply({"turnId": turn})
            continue
        if behavior == "rejected":
            emit({"id": msg["id"], "error": {"code": -32602, "message": "turn already ended"}})
        else:
            reply({"turnId": "wrong-turn" if behavior == "mismatch" else turn})
        complete()
    elif method == "session/new":
        reply({"sessionId": thread})
    elif method == "session/set_mode":
        assert p["modeId"] == "plan"
        reply({})
    elif method == "session/prompt":
        import time
        deadline = time.monotonic() + 10
        while not gate.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        prompt_id = msg["id"]
        emit({"id": 900, "method": "session/request_permission", "params": {"sessionId": thread}})
    elif msg.get("id") == 900:
        assert msg["result"]["outcome"]["outcome"] == "cancelled"
        question = "\n⚠ This service has been disabled in this account for violation of Terms of Service.\n"
        for session, text in [("another", "secret"), (thread, question if behavior == "notice" else "Gemini 原文\n")]:
            event("session/update", {"sessionId": session, "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}})
        emit({"id": prompt_id, "result": {"stopReason": "end_turn"}})
