"""Generate pbm-mcp L1/L2 architecture diagrams as one HTML file."""
import sys
from html import escape

PAPER = "#faf8f2"
INK = "#1a1a1a"
MUTED = "#4b4d4f"
SOFT = "#7b828f"
ACCENT = "#ff612b"
ACCENT_TXT = "#c44116"
LINK = "#0c55b8"
NAVY_RGB = "0,38,119"
SANS = "'Optum Sans', 'Geist', system-ui, sans-serif"
MONO = "'Geist Mono', ui-monospace, monospace"

KINDS = {
    "focal": ("rgba(255,97,43,0.08)", ACCENT, None),
    "backend": ("#ffffff", INK, None),
    "store": ("rgba(26,26,26,0.05)", MUTED, None),
    "external": ("rgba(26,26,26,0.03)", "rgba(26,26,26,0.30)", None),
    "user": ("rgba(75,77,79,0.10)", SOFT, None),
    "optional": ("rgba(26,26,26,0.02)", "rgba(26,26,26,0.35)", "4,3"),
}
TAG_COLOR = {"focal": ACCENT_TXT, "backend": INK, "store": MUTED,
             "external": MUTED, "user": MUTED, "optional": MUTED}


def r4(v):
    return int((v + 3) // 4 * 4)


def node(x, y, w, h, kind, tag, name, subs=(), name_y=None):
    fill, stroke, dash = KINDS[kind]
    d = f' stroke-dasharray="{dash}"' if dash else ""
    tw = r4(len(tag) * 6 + 12)
    tc = TAG_COLOR[kind]
    cx = x + w // 2
    ny = name_y if name_y is not None else y + h // 2 + (4 if subs else 4) - 8 * len(subs) + 8
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"{d}/>',
        f'<rect x="{x+8}" y="{y+8}" width="{tw}" height="12" rx="2" fill="none" stroke="{tc}" stroke-opacity="0.4" stroke-width="0.8"/>',
        f'<text x="{x+8+tw/2:g}" y="{y+17}" fill="{tc}" fill-opacity="0.85" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">{escape(tag)}</text>',
        f'<text x="{cx}" y="{ny}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{escape(name)}</text>',
    ]
    for i, s in enumerate(subs):
        out.append(f'<text x="{cx}" y="{ny + 16 + 14*i}" fill="{MUTED}" font-size="9" font-family="{MONO}" text-anchor="middle">{escape(s)}</text>')
    return "\n".join(out)


def label(cx, line_y, text, below=False):
    w = r4(len(text) * 6 + 8)
    my = line_y + 8 if below else line_y - 20
    return (f'<rect x="{cx - w//2}" y="{my}" width="{w}" height="12" rx="2" fill="{PAPER}"/>'
            f'<text x="{cx}" y="{my+9}" fill="{SOFT}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{escape(text)}</text>')


def side_label(line_x, cy, text, side="right"):
    w = r4(len(text) * 6 + 8)
    mx = line_x + 8 if side == "right" else line_x - 8 - w
    return (f'<rect x="{mx}" y="{cy-6}" width="{w}" height="12" rx="2" fill="{PAPER}"/>'
            f'<text x="{mx + w/2:g}" y="{cy+3}" fill="{SOFT}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">{escape(text)}</text>')


def path(d, kind="muted", dashed=False):
    color, marker = {"muted": (MUTED, "arrow"), "accent": (ACCENT, "arrow-accent"),
                     "link": (LINK, "arrow-link")}[kind]
    extra = ' stroke-dasharray="4,3"' if dashed else ""
    sw = "1" if dashed else "1.2"
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{extra} marker-end="url(#{marker}-{{slug}})"/>'


def zone(x, y, w, h, text):
    lw = r4(len(text) * 6 + 12)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="rgba({NAVY_RGB},0.025)" stroke="rgba({NAVY_RGB},0.16)" stroke-width="0.8"/>'
            f'<rect x="{x+8}" y="{y+4}" width="{lw}" height="12" rx="2" fill="{PAPER}"/>'
            f'<text x="{x+8+lw/2:g}" y="{y+13}" fill="rgba({NAVY_RGB},0.6)" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.14em">{escape(text)}</text>')


def defs(slug):
    m = lambda i, c: f'<marker id="{i}-{slug}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{c}"/></marker>'
    return f'<defs>{m("arrow", MUTED)}{m("arrow-accent", ACCENT)}{m("arrow-link", LINK)}</defs>'


def legend(y, width, items):
    out = [f'<line x1="40" y1="{y-8}" x2="{width-40}" y2="{y-8}" stroke="rgba(26,26,26,0.10)" stroke-width="0.8"/>',
           f'<text x="40" y="{y+12}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">LEGEND</text>']
    x = 112
    for kind, text in items:
        if kind.startswith("line-"):
            k = kind[5:]
            dashed = k.endswith("-dash")
            k = k.replace("-dash", "")
            color = {"muted": MUTED, "link": LINK, "accent": ACCENT}[k]
            da = ' stroke-dasharray="4,3"' if dashed else ""
            out.append(f'<line x1="{x}" y1="{y+8}" x2="{x+24}" y2="{y+8}" stroke="{color}" stroke-width="1.2"{da}/>')
        else:
            fill, stroke, dash = KINDS[kind]
            da = f' stroke-dasharray="{dash}"' if dash else ""
            out.append(f'<rect x="{x}" y="{y+2}" width="24" height="12" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"{da}/>')
        out.append(f'<text x="{x+32}" y="{y+12}" fill="{MUTED}" font-size="9" font-family="{SANS}">{escape(text)}</text>')
        x += 32 + r4(len(text) * 5.6) + 28
    return "\n".join(out)


def svg(slug, w, h, title, desc, body):
    body = body.replace("{slug}", slug)
    return f'''<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{slug}-title {slug}-desc">
<title id="{slug}-title">{escape(title)}</title>
<desc id="{slug}-desc">{escape(desc)}</desc>
{defs(slug)}
<rect width="100%" height="100%" fill="{PAPER}"/>
{body}
</svg>'''


# ---------------------------------------------------------------- L1
DOMAINS = ["health-opportunity", "member-profile", "drug-search", "formulary",
           "claim-history", "savings-center", "pharmacy-search", "accumulators",
           "prior-auth", "drug-pricing", "id-card", "member-consent"]

l1 = []
# arrows first
l1.append(path("M220,176 H360"))
l1.append(label(288, 176, "MCP · HTTP"))
l1.append(path("M600,176 H700", "link"))
l1.append(label(648, 176, "GRAPHQL"))
l1.append(path("M480,336 V228"))
l1.append(side_label(480, 284, "LOAD AT STARTUP"))
l1.append(path("M600,208 H632 Q640,208 640,216 V368 Q640,376 648,376 H700", "muted", dashed=True))
l1.append(side_label(640, 300, "LOCAL DEV", "left"))
# nodes
l1.append(node(40, 136, 180, 80, "user", "USER", "MCP client", ["Cursor · AI agent", "streamable HTTP"]))
l1.append(node(360, 124, 240, 104, "focal", "MCP SERVER", "pbm-mcp", [
    "FastMCP · 127.0.0.1:8000/mcp", "12 namespaces · allowlisted tools", "upstream auth per domain"], name_y=168))
# PBM APIs container
l1.append(f'<rect x="700" y="60" width="260" height="232" rx="6" fill="{PAPER}"/>')
l1.append(f'<rect x="700" y="60" width="260" height="232" rx="6" fill="rgba(26,26,26,0.03)" stroke="rgba(26,26,26,0.30)" stroke-width="1"/>')
l1.append(f'<rect x="708" y="68" width="36" height="12" rx="2" fill="none" stroke="{MUTED}" stroke-opacity="0.4" stroke-width="0.8"/>'
          f'<text x="726" y="77" fill="{MUTED}" fill-opacity="0.85" font-size="7" font-family="{MONO}" text-anchor="middle" letter-spacing="0.08em">EXT</text>')
l1.append(f'<text x="830" y="100" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">PBM GraphQL APIs</text>')
l1.append(f'<text x="830" y="114" fill="{MUTED}" font-size="9" font-family="{MONO}" text-anchor="middle">PBM_&lt;DOMAIN&gt;_BASE_URL</text>')
for i, dname in enumerate(DOMAINS):
    cx = 716 + (i % 2) * 120
    cy = 124 + (i // 2) * 24
    l1.append(f'<rect x="{cx}" y="{cy}" width="108" height="16" rx="2" fill="#ffffff" stroke="rgba(26,26,26,0.14)" stroke-width="0.8"/>'
              f'<text x="{cx+54}" y="{cy+11}" fill="{MUTED}" font-size="8" font-family="{MONO}" text-anchor="middle">{dname}</text>')
l1.append(node(360, 336, 240, 80, "store", "FILES", "Specs · allowlists · .env", ["specs/&lt;domain&gt;/*.yaml".replace("&lt;", "<").replace("&gt;", ">"), "allowlists/<domain>.yaml"]))
l1.append(node(700, 336, 260, 80, "optional", "DEV", "pbm-mock", ["127.0.0.1:8001/v1/<domain>/graphql", "mocks/world · fixtures"]))
# annotation
l1.append(f'<text x="40" y="264" fill="{MUTED}" font-size="14" font-style="italic" font-family="\'Instrument Serif\', serif">Binds localhost only —</text>')
l1.append(f'<text x="40" y="282" fill="{MUTED}" font-size="14" font-style="italic" font-family="\'Instrument Serif\', serif">/mcp has no inbound auth in v1.</text>')
l1.append(legend(464, 1000, [("focal", "Focal system"), ("user", "Client"), ("store", "Config"),
                             ("external", "External API"), ("optional", "Local stand-in"),
                             ("line-link", "Upstream HTTP"), ("line-muted-dash", "Dev alternative")]))
L1 = svg("pbm-l1", 1000, 500, "pbm-mcp system context (L1)",
         "System context showing an MCP client calling the pbm-mcp server, which loads specs and allowlists from disk and calls twelve PBM GraphQL APIs, or the local pbm-mock in development.",
         "\n".join(l1))

# ---------------------------------------------------------------- L2
l2 = []
l2.append(zone(200, 88, 544, 144, "AT STARTUP"))
l2.append(zone(200, 324, 728, 140, "PER TOOL CALL"))
# startup arrows
l2.append(path("M352,164 H408"))
l2.append(path("M536,164 H592"))
l2.append(path("M656,208 V356", "accent"))
l2.append(side_label(656, 284, "REGISTERS TOOLS"))
l2.append(path("M320,120 V72 Q320,64 328,64 H832 Q840,64 840,72 V356", "muted", dashed=True))
l2.append(label(580, 64, "AUTH MODE · BASE_URL"))
# request arrows
l2.append(path("M168,400 H224"))
l2.append(label(196, 400, "CALL"))
l2.append(path("M352,400 H408"))
l2.append(label(380, 400, "ROUTE"))
l2.append(path("M536,400 H592"))
l2.append(label(564, 400, "WRAP"))
l2.append(path("M720,400 H776"))
l2.append(label(748, 400, "SEND"))
l2.append(path("M904,400 H960", "link"))
l2.append(label(932, 400, "POST"))
l2.append(path("M472,444 V488 Q472,496 464,496 H112 Q104,496 104,488 V444", "muted", dashed=True))
l2.append(label(288, 496, "REDACTED ERROR"))
# nodes
l2.append(node(224, 120, 128, 88, "store", "CFG", "Settings · catalog", ["config.py · .env", "12 domain ids"]))
l2.append(node(408, 120, 128, 88, "backend", "LOAD", "Spec loaders", ["openapi · graphql", "introspection"]))
l2.append(node(592, 120, 128, 88, "focal", "GATE", "Allowlist gate", ["allowlists/*.yaml", "deny by default"]))
l2.append(node(40, 356, 128, 88, "user", "USER", "MCP client", ["tools/call", "{ns}_{operation}"]))
l2.append(node(224, 356, 128, 88, "backend", "APP", "pbm-mcp parent", ["FastMCP :8000/mcp", "mounts namespaces"]))
l2.append(node(408, 356, 128, 88, "backend", "MW", "UpstreamGuard", ["http.py · redact.py", "op name · safe errs"]))
l2.append(node(592, 356, 128, 88, "backend", "TOOL", "Domain tool", ["GraphQL op / route", "×12 sub-servers"]))
l2.append(node(776, 356, 128, 88, "backend", "HTTP", "Upstream client", ["httpx2 + auth/*", "LoggingTransport"]))
l2.append(node(960, 356, 128, 88, "external", "EXT", "PBM API", ["/v1/<domain>/graphql", "or pbm-mock"]))
l2.append(legend(552, 1128, [("focal", "Focal control"), ("backend", "Component"), ("store", "Config"),
                             ("user", "Client"), ("external", "External"),
                             ("line-accent", "Tool registration"), ("line-link", "Upstream HTTP"),
                             ("line-muted-dash", "Config / error path")]))
L2 = svg("pbm-l2", 1128, 588, "pbm-mcp components (L2)",
         "Component view of pbm-mcp: at startup, settings and the domain catalog feed spec loaders and an allowlist gate that registers tools; per tool call, the parent server routes through UpstreamGuard to a domain tool and an authenticated, logged HTTP client that calls the PBM API.",
         "\n".join(l2))

CARD = '''<div class="card"><p class="eyebrow">{eb}</p><div class="card-header"><span class="card-dot {dot}"></span><h3>{h}</h3></div><ul>{items}</ul></div>'''


def card(eb, dot, h, items):
    return CARD.format(eb=eb, dot=dot, h=h, items="".join(f"<li>{i}</li>" for i in items))


cards1 = "".join([
    card("Mount rule", "accent", "A domain mounts only when complete", [
        "Spec present in <code>specs/&lt;domain&gt;/</code> <em>and</em> <code>PBM_&lt;DOMAIN&gt;_BASE_URL</code> set",
        "Both OpenAPI and GraphQL in one domain → skipped",
        "No spec → process still starts, zero tools"]),
    card("Upstream auth", "link", "Per-domain credential strategy", [
        "<code>none</code>, <code>api-key</code>, <code>bearer-env</code>, <code>forward</code>",
        "<code>forward</code> copies the inbound MCP <code>Authorization</code> header",
        "<code>client-credentials</code> is a slot only — domain skipped"]),
    card("Member data", "ink", "Bodies never logged", [
        "Logs: domain, operation, status, latency",
        "URLs suppressed (can carry member ids)",
        "Errors truncated to 500 chars, secrets redacted"]),
])
cards2 = "".join([
    card("Allowlist gate", "accent", "Deny by default", [
        "Missing / empty allowlist → zero tools",
        "Mutations, non-GET routes, <code>orderIdCard</code>, <code>saveConsent</code> need <code>write: true</code>",
        "Subscriptions never exposed"]),
    card("Request path", "link", "One tool call, end to end", [
        "Tool name <code>{namespace}_{operation}</code> routes to its sub-server",
        "UpstreamGuard tags the operation for logs and sanitises errors",
        "LoggingTransport times every upstream request"]),
    card("Startup skips", "ink", "Logged, never fatal", [
        "<code>no_spec</code>, <code>no_base_url</code>, <code>both_openapi_and_graphql</code>",
        "<code>auth_not_implemented</code>, <code>auth_not_configured</code>",
        "<code>invalid_spec</code> on any loader exception"]),
])

HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>pbm-mcp Architecture</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --paper: {PAPER}; --ink: {INK}; --muted: {MUTED}; --soft: {SOFT};
  --accent: {ACCENT}; --link: {LINK}; --navy: #002677;
  --rule: rgba(26,26,26,0.12);
  --font-sans: {SANS}; --font-serif: 'Instrument Serif', serif; --font-mono: {MONO};
}}
body {{ font-family: var(--font-sans); background: var(--paper); color: var(--ink); padding: 3rem 2rem; }}
.frame {{ max-width: 1200px; margin: 0 auto; }}
.eyebrow {{ font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.5rem; }}
h1 {{ font-family: var(--font-serif); font-size: clamp(1.75rem, 2.4vw + 0.75rem, 2.4rem); font-weight: 400; letter-spacing: -0.02em; line-height: 1.15; }}
.lede {{ color: var(--muted); max-width: 60ch; margin: 0.75rem 0 2.5rem; line-height: 1.5; }}
section {{ margin-bottom: 3.5rem; }}
h2 {{ font-family: var(--font-serif); font-weight: 400; font-size: 1.6rem; margin-bottom: 0.25rem; }}
h2 .lvl {{ color: var(--accent); }}
.sub {{ color: var(--muted); margin-bottom: 1.25rem; font-size: 0.95rem; }}
.diagram {{ overflow-x: auto; }}
svg {{ width: 100%; min-width: 900px; display: block; }}
.cards {{ display: grid; grid-template-columns: 1.1fr 1fr 0.9fr; gap: 1rem; margin-top: 1.5rem; }}
.card {{ background: #fff; border: 1px solid var(--rule); border-radius: 6px; padding: 1.25rem; }}
.card-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.6rem; }}
.card h3 {{ font-size: 0.95rem; font-weight: 600; }}
.card ul {{ list-style: none; font-size: 0.85rem; color: var(--muted); line-height: 1.5; }}
.card li {{ padding: 0.2rem 0; border-top: 1px solid var(--rule); }}
.card li:first-child {{ border-top: none; }}
code {{ font-family: var(--font-mono); font-size: 0.78rem; color: var(--ink); }}
.card-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
.card-dot.accent {{ background: var(--accent); }} .card-dot.link {{ background: var(--link); }} .card-dot.ink {{ background: var(--ink); }}
footer {{ font-family: var(--font-mono); font-size: 0.7rem; color: var(--soft); border-top: 1px solid var(--rule); padding-top: 1rem; }}
@media (max-width: 760px) {{ .cards {{ grid-template-columns: 1fr; }} body {{ padding: 2rem 1rem; }} }}
</style>
</head>
<body>
<div class="frame">
  <p class="eyebrow">Architecture · pbm-mcp v0.1.0</p>
  <h1>pbm-mcp: Pharmacy Benefit APIs as MCP tools</h1>
  <p class="lede">A localhost FastMCP server that turns twelve PBM GraphQL/OpenAPI specs into namespaced, allowlisted tools, and calls the upstream APIs with per-domain credentials.</p>

  <section>
    <p class="eyebrow">Level 1 · System context</p>
    <h2><span class="lvl">L1</span> — Who talks to pbm-mcp</h2>
    <p class="sub">One MCP client, one local server, twelve upstream domains. pbm-mock swaps in for the live hosts during development.</p>
    <div class="diagram">{L1}</div>
    <div class="cards">{cards1}</div>
  </section>

  <section>
    <p class="eyebrow">Level 2 · Components</p>
    <h2><span class="lvl">L2</span> — Inside the server</h2>
    <p class="sub">Startup builds one sub-server per domain behind the allowlist gate; each tool call then flows left to right to the upstream API.</p>
    <div class="diagram">{L2}</div>
    <div class="cards">{cards2}</div>
  </section>

  <footer>Source: pbm-mcp/src/pbm_mcp · server.py, catalog.py, config.py, allowlist.py, *_loader.py, introspection.py, http.py, redact.py, auth/, mock/</footer>
</div>
</body>
</html>
'''

open(sys.argv[1], "w").write(HTML)
print("wrote", sys.argv[1])
