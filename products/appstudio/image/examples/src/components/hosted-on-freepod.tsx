// A small credit in the footer. The app's owner may remove it.
export function HostedOnFreepod() {
  return (
    <a
      href="https://freepod.eu"
      target="_blank"
      rel="noopener"
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
    >
      <span aria-hidden className="size-3 rounded-[3px] bg-gradient-to-br from-[#2563EB] to-[#6D5BFF]" />
      Hosted on Freepod
    </a>
  );
}
