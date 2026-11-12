import { Flag } from "lucide-react";
import type { CampaignContinueMeta } from "../../lib/api";
import type { Msg } from "../../lib/store";
import { RowShell, msgText } from "./RowShell";

/** meta.campaign_continue: a harness message that keeps a campaign going (autopilot's "continue the
 *  phase", a phase start after plan approval, a resume, a rollover request). */
export function CampaignContinueRow({ m }: { m: Msg }) {
  const c = m.meta.campaign_continue as CampaignContinueMeta | undefined;
  const text = msgText(m.content);
  const auto = text.startsWith("Continue phase");
  const label = auto ? "Autopilot: continue" : text.startsWith("[Campaign]") ? "Campaign" : "Campaign: continue";
  return (
    <RowShell icon={<Flag size={13} />} label={label} details={text || undefined}>
      {label}{c?.phase ? ` · phase ${c.phase}` : ""}
    </RowShell>
  );
}
