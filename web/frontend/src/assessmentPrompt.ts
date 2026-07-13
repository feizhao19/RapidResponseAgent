export function buildDefaultAnalysisPrompt(
  post: File,
  pre: File | null,
  autoMatchPre: boolean,
): string {
  if (pre) {
    return `Analysis on the input ${pre.name}, ${post.name}`;
  }
  if (autoMatchPre) {
    return `Analysis on the input ${post.name}`;
  }
  return `Analysis on the input ${post.name}`;
}
