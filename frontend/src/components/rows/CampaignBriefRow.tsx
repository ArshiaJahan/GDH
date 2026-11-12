import { Flag } from "lucide-react";
import type { CampaignBriefMeta } from "../../lib/api";
import type { Msg } from "../../lib/store";
import { RowShell, msgText } from "./RowShell";

/** meta.campaign_brief: the harness-written first message of a campaign session. Stub: WP5
 *  (campaigns) owns the final design. */
export function CampaignBriefRow({ m }: { m: Msg }) {
  const b = m.meta.campaign_brief as CampaignBriefMeta;
  return (
    <RowShell icon={<Flag size={13} />} label="Campaign brief"
      details={<pre className="font-mono text-[11.5px] whitespace-pre-wrap max-h-96 overflow-auto">{msgText(m.content)}</pre>}>
      Campaign brief{b?.title ? `: ${b.title}` : ""}{b?.phase != null ? ` · phase ${b.phase}` : ""}
    </RowShell>
  );
}
