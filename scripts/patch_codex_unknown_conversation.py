from __future__ import annotations

import argparse
from pathlib import Path


def skeleton_for(receiver: str, conversation_id: str) -> str:
    return (
        f"if(!{receiver}.conversations.get({conversation_id})&&"
        f"({receiver}.activateThreadSummary({conversation_id}),!{receiver}.conversations.get({conversation_id}))"
        f"){{let e=Date.now();{receiver}.ensureRecentConversationId({conversation_id}),"
        f"{receiver}.setConversation({{id:{conversation_id},hostId:{receiver}.getHostId(),turns:[],"
        "requests:[],createdAt:e,updatedAt:e,title:null,latestThreadSettings:null,latestModel:``,"
        "latestReasoningEffort:null,previousTurnModel:null,latestCollaborationMode:{mode:`default`,"
        "settings:{reasoning_effort:null,model:``,developer_instructions:null}},"
        f"hasUnreadTurn:{receiver}.getThreadHasUnreadTurn({conversation_id}),threadGoal:null,"
        "threadRuntimeStatus:null,rolloutPath:``,cwd:``,gitInfo:null,resumeState:`resumed`,"
        "latestTokenUsageInfo:null})}"
    )


START_OLD = (
    "if(!this.conversations.get(r)){y.error(`Received turn/started for unknown conversation`,"
    "{safe:{conversationId:r},sensitive:{}});break}this.markConversationStreaming(r),"
)

COMPLETE_OLD = (
    "if(!this.conversations.get(r)){y.error(`Received turn/completed for unknown conversation`,"
    "{safe:{conversationId:r},sensitive:{}});break}let i=null,a=null,o=null;"
)

START_NEW = skeleton_for("this", "r") + "this.markConversationStreaming(r),"
COMPLETE_NEW = skeleton_for("this", "r") + "let i=null,a=null,o=null;"

HOOK_OLD = (
    "if(!this.conversations.has(i)){y.error(`Received ${n.method} for unknown conversation`,"
    "{safe:{conversationId:i}});break}n.method===`hook/started`&&"
)
HOOK_NEW = skeleton_for("this", "i") + "n.method===`hook/started`&&"

ITEM_STARTED_OLD = (
    "if(!this.conversations.get(a)){y.error(`Received item/started for unknown conversation`,"
    "{safe:{conversationId:a},sensitive:{}});break}this.markConversationStreaming(a),"
)
ITEM_STARTED_NEW = skeleton_for("this", "a") + "this.markConversationStreaming(a),"

ITEM_COMPLETED_OLD = (
    "if(!this.conversations.get(a)){y.error(`Received item/completed for unknown conversation`,"
    "{safe:{conversationId:a},sensitive:{}});break}this.updateConversationState(a,t=>{"
)
ITEM_COMPLETED_NEW = skeleton_for("this", "a") + "this.updateConversationState(a,t=>{"

REALTIME_ITEM_OLD = (
    "if(!this.conversations.has(t)){y.error(`Received thread/realtime/itemAdded for unknown conversation`,"
    "{safe:{conversationId:t},sensitive:{}});break}this.markConversationStreaming(t),"
)
REALTIME_ITEM_NEW = skeleton_for("this", "t") + "this.markConversationStreaming(t),"

AUTO_REVIEW_OLD = (
    "if(!t.getConversation(r)){y.error(`Received automatic approval review for unknown conversation`,"
    "{safe:{conversationId:r,targetItemId:e.targetItemId},sensitive:{}});return}t.updateConversationState(r,t=>{"
)
AUTO_REVIEW_NEW = (
    "if(!t.getConversation(r)&&(t.activateThreadSummary(r),!t.getConversation(r))){let n=Date.now();"
    "t.ensureRecentConversationId(r),t.setConversation({id:r,hostId:t.getHostId(),turns:[],"
    "requests:[],createdAt:n,updatedAt:n,title:null,latestThreadSettings:null,latestModel:``,"
    "latestReasoningEffort:null,previousTurnModel:null,latestCollaborationMode:{mode:`default`,"
    "settings:{reasoning_effort:null,model:``,developer_instructions:null}},"
    "hasUnreadTurn:t.getThreadHasUnreadTurn(r),threadGoal:null,threadRuntimeStatus:null,rolloutPath:``,"
    "cwd:``,gitInfo:null,resumeState:`resumed`,latestTokenUsageInfo:null})}"
    "t.updateConversationState(r,t=>{"
)

PATCHES = [
    ("turn/started", START_OLD, START_NEW),
    ("turn/completed", COMPLETE_OLD, COMPLETE_NEW),
    ("hook started/completed", HOOK_OLD, HOOK_NEW),
    ("item/started", ITEM_STARTED_OLD, ITEM_STARTED_NEW),
    ("item/completed", ITEM_COMPLETED_OLD, ITEM_COMPLETED_NEW),
    ("thread/realtime/itemAdded", REALTIME_ITEM_OLD, REALTIME_ITEM_NEW),
    ("automatic approval review", AUTO_REVIEW_OLD, AUTO_REVIEW_NEW),
]


def patch_bundle(bundle: Path) -> tuple[int, list[str]]:
    text = bundle.read_text(encoding="utf-8")
    messages: list[str] = []

    replacements = 0
    for name, old, new in PATCHES:
        if old in text:
            text = text.replace(old, new, 1)
            replacements += 1
            messages.append(f"patched {name} unknown-conversation guard")
        elif new in text:
            messages.append(f"{name} guard already patched")
        else:
            raise RuntimeError(f"could not find {name} unknown-conversation guard")

    bundle.write_text(text, encoding="utf-8")
    return replacements, messages


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patch Codex Desktop's renderer bundle so early turn events create a local conversation skeleton instead of erroring."
    )
    parser.add_argument("extracted_app", type=Path, help="Path produced by @electron/asar extract")
    args = parser.parse_args()

    assets_dir = args.extracted_app / "webview" / "assets"
    bundles = sorted(assets_dir.glob("app-server-manager-signals-*.js"))
    if not bundles:
        raise SystemExit(f"no app-server-manager-signals bundle found under {assets_dir}")

    bundle = bundles[0]
    replacements, messages = patch_bundle(bundle)
    print(f"bundle={bundle}")
    print(f"replacements={replacements}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
