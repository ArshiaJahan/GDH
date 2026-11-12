import { Flag } from "lucide-react";
import type { CampaignContinueMeta } from "../../lib/api";
import type { Msg } from "../../lib/store";
import { RowShell, msgText } from "./RowShell";

/** meta.campaign_continue: autopilot's "continue the phase" message. Stub: WP5 (campaigns) owns
 *  the final design. */
export function CampaignContinueRow({ m }: { m: Msg }) {
  const c = m.meta.campaign_continue as CampaignContinueMeta;
  return (
    <RowShell icon={<Flag size={13} />} label="Autopilot continued" details={msgText(m.content) || undefined}>
      Autopilot: continue{c?.phase != null ? ` phase ${c.phase}` : ""}
    </RowShell>
  );
}
