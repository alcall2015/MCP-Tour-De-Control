/** Renders a model-supplied value as text: strings as they are, anything else as JSON. */
export function text(x: unknown): string {
  return typeof x === "string" ? x : JSON.stringify(x);
}
