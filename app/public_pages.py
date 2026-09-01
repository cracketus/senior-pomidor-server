"""Small public-facing pages served by the Core application.

Keep these pages dependency-free and free of private infrastructure details. They are
intended to remain useful on mobile devices even on a slow connection.
"""

CONTACTS_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta
    name="description"
    content="Timur Shevlyakov — Senior Pomidor / Tomato Brain. Open-source embodied AI for agriculture."
  >
  <meta name="theme-color" content="#173c2b">
  <meta property="og:title" content="Timur Shevlyakov · Senior Pomidor">
  <meta property="og:description" content="Open-source embodied AI for agriculture.">
  <meta property="og:type" content="profile">
  <meta property="og:url" content="https://cracketus.dev/contacts">
  <title>Timur Shevlyakov · Senior Pomidor</title>
  <style>
    :root {
      color-scheme: light;
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f6f1;
      color: #172019;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px 16px;
      background:
        radial-gradient(circle at top right, rgba(207, 230, 210, 0.85), transparent 38rem),
        #f3f6f1;
    }
    main {
      width: min(100%, 540px);
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid #dbe5da;
      border-radius: 22px;
      padding: 28px;
      box-shadow: 0 18px 55px rgba(23, 60, 43, 0.09);
    }
    .eyebrow {
      margin: 0 0 10px;
      color: #52705e;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      font-size: clamp(30px, 8vw, 42px);
      line-height: 1.03;
      letter-spacing: -0.035em;
    }
    h2 {
      margin: 9px 0 0;
      color: #b43a2f;
      font-size: 19px;
      line-height: 1.3;
    }
    .intro {
      margin: 22px 0 0;
      color: #415247;
      font-size: 16px;
      line-height: 1.55;
    }
    .loop {
      margin: 18px 0 0;
      padding: 13px 14px;
      border-left: 3px solid #4d795f;
      border-radius: 0 10px 10px 0;
      background: #f4f8f3;
      color: #294134;
      font-size: 14px;
      line-height: 1.5;
    }
    nav {
      display: grid;
      gap: 10px;
      margin-top: 24px;
    }
    a.button {
      min-height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 13px 15px;
      border: 1px solid #cbd9cd;
      border-radius: 12px;
      color: #173c2b;
      background: #fff;
      font-weight: 700;
      text-decoration: none;
    }
    a.button:hover, a.button:focus-visible {
      border-color: #6d927a;
      background: #f7faf6;
      outline: none;
    }
    a.button.primary {
      border-color: #173c2b;
      background: #173c2b;
      color: #fff;
    }
    .arrow { opacity: 0.65; }
    footer {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
      margin-top: 24px;
      padding-top: 18px;
      border-top: 1px solid #e2e9e1;
      color: #65756a;
      font-size: 12px;
    }
    footer a { color: inherit; }
    @media (max-width: 420px) {
      main { padding: 23px 19px; border-radius: 18px; }
      body { padding: 14px; }
    }
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">Senior Pomidor · Tomato Brain</p>
    <h1>Timur Shevlyakov</h1>
    <h2>Open-source embodied AI for agriculture.</h2>

    <p class="intro">
      I am building Senior Pomidor: an open, local-first decision layer that turns
      agricultural observations into explainable, safe actions in the physical world.
    </p>

    <p class="loop">observe → understand → predict → decide → act → measure the outcome</p>

    <nav aria-label="Contact links">
      <a
        class="button primary"
        href="https://www.linkedin.com/in/timur-shevlyakov/"
        target="_blank"
        rel="noreferrer"
      >
        <span>Connect on LinkedIn</span><span class="arrow" aria-hidden="true">↗</span>
      </a>
      <a
        class="button"
        href="https://github.com/cracketus/senior-pomidor"
        target="_blank"
        rel="noreferrer"
      >
        <span>Senior Pomidor on GitHub</span><span class="arrow" aria-hidden="true">↗</span>
      </a>
      <a
        class="button"
        href="https://github.com/cracketus"
        target="_blank"
        rel="noreferrer"
      >
        <span>GitHub profile</span><span class="arrow" aria-hidden="true">↗</span>
      </a>
      <a class="button" href="/contacts.vcf">
        <span>Save contact</span><span class="arrow" aria-hidden="true">↓</span>
      </a>
    </nav>

    <footer>
      <span>Senior Pomidor is an open research project.</span>
      <a href="https://cracketus.dev/">cracketus.dev</a>
    </footer>
  </main>
</body>
</html>
"""


CONTACTS_VCARD = """\
BEGIN:VCARD\r
VERSION:3.0\r
FN:Timur Shevlyakov\r
N:Shevlyakov;Timur;;;\r
URL:https://cracketus.dev/contacts\r
URL:https://www.linkedin.com/in/timur-shevlyakov/\r
URL:https://github.com/cracketus\r
NOTE:Senior Pomidor / Tomato Brain - open-source embodied AI for agriculture.\r
END:VCARD\r
"""
