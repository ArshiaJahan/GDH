import { Flag } from "lucide-react";
import type { CampaignBriefMeta } from "../../lib/api";
import { actions, type Msg } from "../../lib/store";
import { SafeMarkdown } from "../SafeMarkdown";
import { RowShell, msgText } from "./RowShell";

/** meta.campaign_brief: the first message of a campaign session, assembled by the harness from the
 *  campaign file (phase 0 is the plan session). Collapsed to one line; the brief shows on expand. */
export function CampaignBriefRow({ m }: { m: Msg }) {
  const b = m.meta.campaign_brief as CampaignBriefMeta | undefined;
  const what = b?.phase ? `phase ${b.phase}` : "plan";
  return (
    <RowShell icon={<Flag size={13} />} label="Campaign brief"
      details={
        <div className="text-[12.5px] max-h-[28rem] overflow-auto scroll-thin">
          <div className="prose-sm"><SafeMarkdown text={msgText(m.content)} /></div>
          {b?.campaign_id && (
            <button className="mt-1 text-action hover:underline" onClick={() => actions.go("campaigns", { id: b.campaign_id })}>Open the campaign</button>
          )}
        </div>
      }>
      Campaign brief{b?.title ? `: ${b.title}` : ""} · {what}
    </RowShell>
  );
}
