/** Placeholder token → original segment. In-memory only for one pipeline run. */
export type MaskingMap = Map<string, string>;

const EMAIL_REGEX =
  /[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+/g;

/**
 * Collects masked tokens for Server 2 classify; never persisted.
 * Emails are tokenized in free text; whole display names become a single person token.
 */
export class MaskingSession {
  private emailSeq = 1;
  private personSeq = 1;
  readonly map: MaskingMap = new Map();

  maskEmailsInText(text: string): string {
    return text.replace(EMAIL_REGEX, (match) => {
      const token = `[EMAIL_${this.emailSeq++}]`;
      this.map.set(token, match);
      return token;
    });
  }

  maskDisplayName(name: string | null | undefined): string | null {
    if (!name?.trim()) {
      return null;
    }
    const token = `[PERSON_${this.personSeq++}]`;
    this.map.set(token, name.trim());
    return token;
  }

  unmaskStrings(values: string[]): string[] {
    if (values.length === 0) {
      return values;
    }
    const entries = [...this.map.entries()].sort((a, b) => b[0].length - a[0].length);
    return values.map((value) => {
      let out = value;
      for (const [token, original] of entries) {
        out = out.split(token).join(original);
      }
      return out;
    });
  }
}
