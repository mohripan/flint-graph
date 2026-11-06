# ADR 0063: Child sessions in the assistant

Status: accepted (2026-11-06)

## Context

One long conversation is a poor fit for large work. A whole cast, or several chapters, belong in
separate conversations that stay connected to the one that asked for them. The creator wanted
the shape of Claude's desktop app: a parent conversation with child sessions nested under it,
which also keeps a long project's conversation list readable.

## Decision

1. **Conversations form a tree one level deep.** `narrative_assistant_threads` gains
   `parent_thread_id`, `task` and `origin` (migration 0048). A composite foreign key keeps a
   parent in the same project and workspace. A child cannot have children, and a parent can have
   at most 32. `GET /threads` lists roots with their children nested, and says which are working.
2. **The creator can start one.** **New child session** in the chat header makes the next message
   start a conversation under the current one, and that message is its task.
3. **The assistant can start them too.** `start_child_session` is an action
   ([ADR 0061](0061-assistant-runs-generation.md)), up to 8 per proposal. It creates the session and
   posts its task as the first message, through the normal admission: the creator's credits, the
   workspace's reply limit and the audit trail. A busy assistant leaves it `pending`, so sessions
   run one after another by themselves. It inherits the asking turn's automatic-generation choice,
   and alongside story edits it waits for Accept, because it works from the saved story.
4. **Child sessions cannot start their own, and this is enforced by the grammar.** A prompt rule
   was not enough: the live model tried to start another session instead of doing its task. Inside
   a child session, `start_child_session` is not in the output schema at all.
5. **Sessions stay connected through the log** ([ADR 0060](0060-assistant-thread-event-log.md)).
   A child is told it is one, its task, and what its parent did, folded from the parent's log. A
   parent's log gets `child.started` and `child.updated` (replied, failed, stopped, accepted,
   rejected), so its next turn knows what its children did. These are written in the transaction
   of the change they report.
6. **A child's changes are reviewed like any others.** Proposals in a child need Accept and rebase
   the same way, so two sessions touching the same record end in the existing conflict flow.

## Rejected

- **Free-form nesting.** It needs recursive queries and a tree UI nobody asked for. The reference
  is one level, and one level cannot run away from a model that keeps delegating.
- **Sharing one conversation history between parent and child.** It would defeat the point: each
  stays focused and cheap to prompt. They share a summary from the log.
- **Running children in parallel.** The reply limit exists because the local GPU runs one model
  call at a time. Sessions queue through the existing action dispatcher, and an operator who raises
  the limit gets concurrency without any change here.
- **A dialog asking for a title and task.** The first message already says what the session is for.

## Consequences

- Each session started costs a reply's credits, up to 8 per proposal without another click when
  automatic generation is on.
- While a session runs, a message elsewhere in the workspace can be told to wait: the existing
  per-workspace reply limit (one by default) applies across all sessions.
- There is no delete or archive for sessions, as for conversations generally.
- An action's "It has replied" means its first reply ended. It may be a question, or a proposal
  waiting for review, so the creator still opens the session.
