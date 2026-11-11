export interface Skill {
  name: string;
  tokens: number;
  body_tokens: number;
  desc_tokens: number;
  desc_characters: number;
  warnings: string[];
}

export interface Agent {
  name: string;
  instructions_tokens: number;
  referenced_skills_count: number;
  referenced_skills_tokens: number;
  total_tokens: number;
  mode: string;
}

export interface Provider { files: number; total_tokens: number }

export interface Profile {
  encoding: string;
  skills: Skill[];
  agents: Agent[];
  targets: Record<string, Provider>;
  summary: {
    skills_count: number;
    agents_count: number;
    names_only_floor_tokens: number;
    descriptions_ceiling_tokens: number;
    skills_total_tokens: number;
  };
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const numbers = (value: Record<string, unknown>, fields: string[]) =>
  fields.every((field) => Number.isSafeInteger(value[field]) && (value[field] as number) >= 0);

// Validate the transport boundary without transforming or recomputing kit data.
export function parseProfile(value: unknown): Profile {
  if (!record(value) || typeof value.encoding !== 'string' ||
      !Array.isArray(value.skills) || !Array.isArray(value.agents) ||
      !record(value.targets) || !record(value.summary) ||
      !numbers(value.summary, ['skills_count', 'agents_count', 'names_only_floor_tokens',
        'descriptions_ceiling_tokens', 'skills_total_tokens']) ||
      !value.skills.every((skill: unknown) => record(skill) && typeof skill.name === 'string' &&
        numbers(skill, ['tokens', 'body_tokens', 'desc_tokens', 'desc_characters']) &&
        Array.isArray(skill.warnings) && skill.warnings.every((warning: unknown) => typeof warning === 'string')) ||
      !value.agents.every((agent: unknown) => record(agent) && typeof agent.name === 'string' &&
        typeof agent.mode === 'string' && numbers(agent, ['instructions_tokens', 'referenced_skills_count',
          'referenced_skills_tokens', 'total_tokens'])) ||
      !Object.values(value.targets).every((provider) => record(provider) && numbers(provider, ['files', 'total_tokens']))) {
    throw new Error('The server returned an unexpected profile format.');
  }
  return value as unknown as Profile;
}

export const formatNumber = (value: number) => new Intl.NumberFormat('en-US').format(value);
export const formatPercent = (tokens: number, budget: number) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(tokens / budget * 100);

export const providerNames: Record<string, string> = {
  claude: 'Claude Code', codex: 'Codex', cursor: 'Cursor', opencode: 'OpenCode',
  windsurf: 'Windsurf', gemini: 'Gemini', 'grok-bot': 'Grok Bot', copilot: 'Copilot',
  zed: 'Zed', continue: 'Continue', cline: 'Cline',
};
