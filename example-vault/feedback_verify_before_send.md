---
name: feedback_verify_before_send
description: Never send an outbound message without explicit approval; show a draft and wait.
metadata:
  type: feedback
  enforcement: pinned
---

Never send anything outbound (email, chat, comment) without explicit approval. Show the draft,
wait for a "send" confirmation, then act.

**Why:** Outbound messages are hard to reverse and represent the user to others.

**How to apply:** This is a pinned rule (always in the hot-set, one tier below hook). It is the
approval gate for anything the [[project_second_brain_launch]] agent produces for a human.
