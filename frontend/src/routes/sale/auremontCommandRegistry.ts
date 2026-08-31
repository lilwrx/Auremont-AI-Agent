export type AuremontCommandId = "customer-summary";

export interface AuremontCommandDefinition {
  id: AuremontCommandId;
  trigger: string;
  title: string;
  description: string;
  keywords: readonly string[];
  privacy: "sale-only";
}

/**
 * Single source of truth for Sale-only @ commands.
 *
 * Add future commands here, then add their execution handler in LiveChatPage. Keeping
 * discovery metadata separate from the chat UI makes the command palette scale without
 * accumulating one-off input checks and menu markup.
 */
export const AUREMONT_COMMANDS: readonly AuremontCommandDefinition[] = [
  {
    id: "customer-summary",
    trigger: "@Auremont tóm tắt khách hàng",
    title: "Tóm tắt khách hàng",
    description: "Gom hội thoại AI và Sale thành hồ sơ bàn giao; khách hàng không nhìn thấy.",
    keywords: ["tóm tắt", "khách hàng", "hồ sơ", "bàn giao", "lịch sử chat"],
    privacy: "sale-only",
  },
];

export function normalizeAuremontCommand(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();
}

export function isInternalCommandInput(value: string): boolean {
  return normalizeAuremontCommand(value).startsWith("@");
}

export function findAuremontCommand(value: string): AuremontCommandDefinition | undefined {
  const normalized = normalizeAuremontCommand(value);
  return AUREMONT_COMMANDS.find((command) => normalizeAuremontCommand(command.trigger) === normalized);
}

export function filterAuremontCommands(value: string): readonly AuremontCommandDefinition[] {
  const normalized = normalizeAuremontCommand(value);
  if (!normalized.startsWith("@")) return [];

  let query = normalized.slice(1).trim();
  if (query === "auremont") query = "";
  else if (query.startsWith("auremont ")) query = query.slice("auremont ".length).trim();
  if (!query) return AUREMONT_COMMANDS;

  const tokens = query.split(/\s+/).filter(Boolean);
  return AUREMONT_COMMANDS.filter((command) => {
    const searchable = normalizeAuremontCommand(
      [command.trigger.slice(1), command.title, command.description, ...command.keywords].join(" "),
    );
    return tokens.every((token) => searchable.includes(token));
  });
}
