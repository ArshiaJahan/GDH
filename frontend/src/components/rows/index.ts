import type { ComponentType } from "react";
import type { Msg } from "../../lib/store";
import { CampaignBriefRow } from "./CampaignBriefRow";
import { CampaignContinueRow } from "./CampaignContinueRow";
import { GateRow } from "./GateRow";
import { SkillLoadRow } from "./SkillLoadRow";
import { TaskContextRow } from "./TaskContextRow";

/** Harness-written messages Chat shows with their own row instead of a chat bubble, by the meta
 *  key that marks them (first match wins). Each component takes { m }. */
export const META_ROWS: [string, ComponentType<{ m: Msg }>][] = [
  ["skill_load", SkillLoadRow],
  ["gate", GateRow],
  ["campaign_brief", CampaignBriefRow],
  ["campaign_continue", CampaignContinueRow],
  ["task_context", TaskContextRow],
];

export function metaRow(m: Msg): ComponentType<{ m: Msg }> | null {
  for (const [key, C] of META_ROWS) if (m.meta?.[key] != null && m.meta[key] !== false) return C;
  return null;
}
