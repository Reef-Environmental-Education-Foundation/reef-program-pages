/* ============================================================
   REEF Program Pages — shared render shell
   ------------------------------------------------------------
   One script, reused by every booking page (Ocean Explorers
   Expeditions and Facility Rentals alike). A booking page is:

     index.html   <- includes styles.css + render.js + data.js
     data.js      <- sets window.BOOKING_DATA (see schema below)

   render.js reads window.BOOKING_DATA and builds the whole page.
   Nothing in this file should change per booking - if a booking
   needs different structure, that's a schema gap to fix here,
   not a one-off edit to copy across every booking page.

   DATA SCHEMA (fields marked optional can be omitted):

   docType: "proposal" is a completely separate rendering mode — the
   advanced six-section customer proposal experience (ported from the
   Dropbox review build). It reads only `data.proposal` (plus the
   shared `meta.sampleFlag` / `assetDepth` fields) and ignores
   everything else below. See the schema comment directly above
   renderAdvancedProposal() further down this file for its shape.
   Everything below this point describes docType "pretrip" (the
   confirmed/pre-trip page).
   {
     docType: "pretrip" | "proposal",
     meta: { sampleFlag: bool, sampleFlagText: string (optional) },
     program: {
       name, track, groupName, schoolOrg, gradeLevel, groupSize,
       location,
       dates: { label: "Draft"|"Confirmed", range: string }
     },
     contacts: {
       educatorName, educatorPhone (optional), educatorEmail (optional),
       reefEducatorName, reefPhone, reefEmail
     },
     hero: {
       eyebrowTag, headline, promise,
       imageUrl (optional): path to a REEF-owned, non-people background photo,
         relative to this booking's own index.html (e.g. "../../assets/photos/reef-shark.jpg").
         Omit to use the default ocean gradient treatment (no photo needed).
       imageCredit (optional): small on-image credit line, e.g. "Photo: Jeffrey Haines / REEF".
     },
     welcome: { body: [string, ...], signOff },
     glanceNote (optional),
     days: [
       {
         dayNumber, totalDays, title, theme,
         morningLabel, afternoonLabel, learningOutcome,
         blocks: [ { time, tag, title, description } ],
         studentsWill: [string, ...],
         bring (optional), note (optional)
       }
     ],
     whatStudentsWillDo (optional): [ { verb, text } ],
     gear: {
       groups: [ { title, items: [ { label, level: "required"|"recommended"|undefined } ] } ]
     },
     flexNote,
     finalReminders: { arrivalTime, parking, reefContact, questionsEmail },

     // ---- Action Needed banner (optional) ----
     // Shown directly under the hero ONLY when customer action is actually
     // required right now. Leave this out entirely (or set show:false) once
     // there is nothing pending — do not show it "just in case".
     actionNeeded (optional): {
       show: bool,
       headline: string,             // e.g. "Your agreement is ready to sign"
       detail: string,                // one or two sentences of context
       ctaText: string,               // button label, e.g. "Review & Sign Agreement"
       ctaUrl: string,                // where the button goes (usually agreement.zohoSignUrl)
     },

     // ---- Agreement / Contract status (optional but expected once a proposal is sent) ----
     // Mirrors the REEF Bookings "Agreement/Contract Status" field exactly:
     // "Not Sent" | "Sent" | "Signed" | "Declined".
     agreement (optional): {
       status: "Not Sent" | "Sent" | "Signed" | "Declined",
       zohoSignUrl (optional): string,  // the Zoho Sign link for this booking's agreement.
         // IMPORTANT (architecture, do not change): this page never embeds or
         // becomes the signed contract itself. It only links out to Zoho Sign,
         // which is REEF's actual e-signature system of record. The signed
         // PDF lives in Zoho Sign, not here.
       lastUpdated (optional): string,  // e.g. "Sent Aug 28, 2026"
     },

     // ---- Next Steps checklist (optional) ----
     // A short, explicit list of what still needs to happen. If omitted,
     // a sensible default list is shown based on agreement.status.
     nextSteps (optional): { items: [string, ...] },

     proposal (only when docType === "proposal"): {
       whyItWorks: [ { title, text } ],
       nextSteps: [ string, ... ]
     }
   }
   ============================================================ */

(function () {
  "use strict";

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      if (key === "class") node.className = attrs[key];
      else if (key === "html") node.innerHTML = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function mount(id, node) {
    const target = document.getElementById(id);
    if (target && node) target.appendChild(node);
  }

  function placeholder(value, fallback) {
    return value && String(value).trim().length ? value : (fallback || "[confirm from booking data]");
  }

  // ---------------- SAMPLE FLAG ----------------
  function renderSampleFlag(data) {
    if (!data.meta || !data.meta.sampleFlag) return;
    mount("sample-flag", el("div", { class: "sample-flag" }, [
      el("strong", {}, ["SAMPLE FORMAT"]),
      "  ·  " + (data.meta.sampleFlagText ||
        "Illustrative content for design reference — not a confirmed itinerary. Times, activities, and order are subject to change."),
    ]));
  }

  // ---------------- LOGO ----------------
  // Uses the real REEF reversed-white logo (assets/reef-logo-white.png,
  // from REEF's Brand Kit) by default. A booking's data.js can override
  // with hero.logoUrl (a path relative to that booking's own index.html)
  // if a different mark is ever needed; hero.logoFallbackText swaps in a
  // plain text wordmark instead, in case the image file is ever missing.
  function renderLogo(data) {
    const hero = (data && data.hero) || {};
    if (hero.logoFallbackText) {
      return el("div", { class: "hero-logo", style: "font-family:'Fraunces',Georgia,serif;font-weight:700;font-size:24px;color:#fff;letter-spacing:.02em;" }, ["REEF"]);
    }
    const url = hero.logoUrl || defaultLogoPath();
    return el("img", { class: "hero-logo", src: url, alt: "REEF Environmental Education Foundation" });
  }

  // Booking pages live at bookings/<slug>/index.html (2 levels deep);
  // the root index.html is 0 levels deep. Work out the right relative
  // path to assets/ from wherever this script is running.
  function defaultLogoPath() {
    const depth = (window.BOOKING_DATA && window.BOOKING_DATA.assetDepth) || 0;
    return "../".repeat(depth) + "assets/reef-logo-white.png";
  }

  // ---------------- HERO ----------------
  function renderHero(data) {
    const p = data.program || {};
    const hero = data.hero || {};
    const dates = p.dates || {};

    const chips = [
      ["Group", p.groupName],
      ["Dates", (dates.label ? dates.label + " — " : "") + placeholder(dates.range)],
      ["Grade Level", p.gradeLevel],
      ["Location", p.location || "REEF Campus, Key Largo"],
    ].map(function (pair) {
      return el("div", { class: "chip" }, [
        el("div", { class: "eyebrow" }, [pair[0]]),
        el("div", { class: "value" }, [placeholder(pair[1])]),
      ]);
    });

    const heroClass = "hero" + (hero.imageUrl ? " hero-has-image" : "");
    const heroStyle = hero.imageUrl ? "background-image:url('" + hero.imageUrl + "');" : "";

    mount("hero", el("div", { class: heroClass, style: heroStyle }, [
      el("div", { class: "hero-top" }, [
        renderLogo(data),
        el("div", { class: "hero-kicker" }, [(hero.kicker || "OCEAN EXPLORERS\nEXPEDITION PACKET").split("\n").join(" ")]),
      ]),
      el("div", { class: "hero-body" }, [
        el("span", { class: "hero-eyebrow" }, [hero.eyebrowTag || p.track || "REEF Program"]),
        el("h1", {}, [hero.headline || p.name || "Program Itinerary"]),
        el("p", { class: "promise" }, [hero.promise || ""]),
      ]),
      el("div", { class: "hero-meta" }, chips),
      hero.imageUrl && hero.imageCredit ? el("div", { class: "hero-photo-credit" }, [hero.imageCredit]) : null,
    ]));
  }

  // ---------------- MINI NAV (persistent wayfinding) ----------------
  // Auto-built from which sections actually have content, unless the
  // booking's data.js supplies an explicit `nav` array of { label, targetId }.
  function buildNavItems(data) {
    if (data.nav && data.nav.length) return data.nav;
    const items = [{ label: "Overview", targetId: "welcome" }];
    if ((data.days || []).length) items.push({ label: "Daily Schedule", targetId: "day-by-day" });
    if (data.gear && (data.gear.groups || []).length) items.push({ label: "What to Bring", targetId: "gear" });
    items.push({ label: "Forms & Next Steps", targetId: "next-steps" });
    return items;
  }

  function renderMiniNav(data) {
    const items = buildNavItems(data);
    if (!items.length) return;
    mount("mini-nav", el("div", { class: "mini-nav" }, [
      el("div", { class: "mini-nav-inner" }, items.map(function (item) {
        return el("a", { class: "mini-nav-link", href: "#" + item.targetId }, [item.label]);
      })),
    ]));
  }

  // ---------------- ACTION NEEDED BANNER ----------------
  // Only rendered when data.actionNeeded.show is explicitly true — a
  // booking with nothing pending should simply omit this block.
  function renderActionNeeded(data) {
    const a = data.actionNeeded;
    if (!a || !a.show) return;
    const cta = a.ctaUrl
      ? el("a", { class: "action-needed-cta", href: a.ctaUrl, target: "_blank", rel: "noopener" }, [a.ctaText || "Take Action"])
      : null;
    mount("action-needed", el("div", { class: "action-needed" }, [
      el("div", { class: "action-needed-icon" }, ["!"]),
      el("div", { class: "action-needed-body" }, [
        el("div", { class: "action-needed-headline" }, [a.headline || "Action needed"]),
        el("div", { class: "action-needed-detail" }, [a.detail || ""]),
      ]),
      cta,
    ]));
  }

  // ---------------- TRIP SNAPSHOT ----------------
  function renderSnapshot(data) {
    const p = data.program || {};
    const c = data.contacts || {};
    const fields = [
      ["Program", p.name],
      ["Group Size", p.groupSize],
      ["REEF Contact", c.reefEducatorName],
      ["Primary Contact", c.educatorName],
    ];
    mount("snapshot", el("div", { class: "snapshot-bar" },
      fields.map(function (pair) {
        return el("div", {}, [
          el("div", { class: "eyebrow" }, [pair[0]]),
          el("div", { class: "value" }, [placeholder(pair[1])]),
        ]);
      })
    ));
  }

  // ---------------- WELCOME ----------------
  function renderWelcome(data) {
    const welcome = data.welcome || {};
    const body = welcome.body || [];
    mount("welcome", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("h2", {}, ["Welcome to REEF Ocean Explorers"]),
        ]),
        el("div", { class: "welcome-body" }, body.map(function (para) {
          return el("p", { style: "margin-bottom:16px;color:var(--ink);font-size:15.5px;" }, [para]);
        }).concat(welcome.signOff ? [
          el("p", { style: "font-style:italic;color:var(--slate);margin-top:20px;" }, ["— " + welcome.signOff]),
        ] : [])),
      ]),
    ]));
  }

  // ---------------- GLANCE TABLE ----------------
  function renderGlance(data) {
    const days = data.days || [];
    if (!days.length) return;
    const rows = days.map(function (day) {
      return el("tr", {}, [
        el("td", { class: "day-cell" }, ["Day " + day.dayNumber]),
        el("td", { class: "theme-cell" }, [day.title || ""]),
        el("td", {}, [day.morningLabel || ""]),
        el("td", {}, [day.afternoonLabel || ""]),
        el("td", {}, [day.learningOutcome || ""]),
      ]);
    });
    mount("glance", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("span", { class: "eyebrow" }, ["EXPEDITION AT A GLANCE"]),
          el("h2", {}, [days.length + " day" + (days.length > 1 ? "s" : "") + ", one Florida Keys Expedition"]),
          el("p", { class: "dek" }, [data.glanceNote ||
            "A quick-scan summary for planning. Full detail — including “students will” outcomes and gear notes — follows on the day-by-day pages."]),
        ]),
        // Wrapped in a scroll container so a wide table scrolls on its own on
        // narrow viewports instead of stretching the whole page sideways
        // (pre-existing mobile overflow bug, fixed here — same pattern
        // already used for the mini-nav).
        el("div", { class: "table-scroll" }, [
          el("table", { class: "glance-table" }, [
            el("thead", {}, [el("tr", {}, ["Day", "Theme", "Morning", "Afternoon", "Learning Outcome"].map(function (h) {
              return el("th", {}, [h]);
            }))]),
            el("tbody", {}, rows),
          ]),
        ]),
      ]),
    ]));
  }

  // ---------------- DAY-BY-DAY ----------------
  function renderDayCard(day) {
    const blocks = (day.blocks || []).map(function (b) {
      return el("div", { class: "time-block" }, [
        el("div", { class: "time" }, [b.time || ""]),
        el("div", {}, [
          b.tag ? el("span", { class: "tag" }, [b.tag]) : null,
          el("h4", {}, [b.title || ""]),
          el("p", { class: "desc" }, [b.description || ""]),
        ]),
      ]);
    });

    const outcomes = (day.studentsWill || []).length
      ? el("div", { class: "outcomes-box" }, [
          el("span", { class: "eyebrow" }, ["STUDENTS WILL"]),
          el("ul", {}, day.studentsWill.map(function (line) { return el("li", {}, [line]); })),
        ])
      : null;

    const footerBits = [];
    if (day.bring) footerBits.push(el("div", { class: "bring-line" }, [el("strong", {}, ["Bring: "]), day.bring]));
    if (day.note) footerBits.push(el("div", {}, [el("strong", {}, ["Note: "]), day.note]));

    return el("div", { class: "day-card" }, [
      el("div", { class: "day-card-head" }, [
        el("div", { class: "day-of" }, ["DAY " + day.dayNumber + " OF " + (day.totalDays || day.dayNumber)]),
        el("h3", {}, [day.title || ""]),
        day.theme ? el("div", { class: "theme-line" }, [day.theme]) : null,
      ]),
      el("div", {}, blocks),
      outcomes,
      footerBits.length ? el("div", { class: "day-footer" }, footerBits) : null,
    ]);
  }

  function renderDayByDay(data) {
    const days = data.days || [];
    if (!days.length) return;
    mount("day-by-day", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("span", { class: "eyebrow" }, ["DAY-BY-DAY ITINERARY"]),
          el("h2", {}, [days.length > 1 ? ("Day 1–" + days.length + " in detail") : "Day 1 in detail"]),
        ]),
        el("div", {}, days.map(renderDayCard)),
      ]),
    ]));
  }

  // ---------------- WHAT STUDENTS WILL DO (deduped) ----------------
  function deriveWhatStudentsWillDo(data) {
    if (data.whatStudentsWillDo) return data.whatStudentsWillDo;
    const verbs = ["Identify", "Observe", "Survey", "Investigate", "Explore", "Practice", "Connect"];
    const seen = {};
    const out = [];
    (data.days || []).forEach(function (day) {
      (day.studentsWill || []).forEach(function (line) {
        const firstWord = (line.split(" ")[0] || "").replace(/[^A-Za-z]/g, "");
        const verb = verbs.indexOf(firstWord) !== -1 ? firstWord : "Practice";
        const key = line.toLowerCase();
        if (!seen[key]) {
          seen[key] = true;
          out.push({ verb: verb, text: line });
        }
      });
    });
    return out.slice(0, 6);
  }

  function renderWhatStudentsWillDo(data) {
    const items = deriveWhatStudentsWillDo(data);
    if (!items.length) return;
    mount("students-will-do", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("span", { class: "eyebrow" }, ["WHAT STUDENTS WILL DO"]),
          el("h2", {}, ["Real participation, not a spectator trip"]),
        ]),
        el("div", { class: "will-grid" }, items.map(function (item) {
          return el("div", { class: "will-card" }, [
            el("span", { class: "verb" }, [item.verb]),
            el("p", {}, [item.text]),
          ]);
        })),
      ]),
    ]));
  }

  // ---------------- GEAR & READINESS ----------------
  function renderGear(data) {
    const gear = data.gear || {};
    const groups = gear.groups || [];
    if (!groups.length) return;
    mount("gear", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("span", { class: "eyebrow" }, ["GEAR & READINESS"]),
          el("h2", {}, ["What to bring, what to prepare"]),
          el("p", { class: "dek" }, ["Pulled from your group's booking details. Required items are necessary to participate; recommended items add comfort."]),
        ]),
        el("div", { class: "gear-grid" }, groups.map(function (group) {
          return el("div", { class: "gear-card" }, [
            el("h4", {}, [group.title]),
            el("ul", {}, (group.items || []).map(function (item) {
              return el("li", {}, [
                item.level ? el("span", { class: "badge " + item.level }, [item.level]) : null,
                " " + item.label,
              ]);
            })),
          ]);
        })),
      ]),
    ]));
  }

  // ---------------- AGREEMENT STATUS PILL ----------------
  const AGREEMENT_PILL_CLASS = {
    "Not Sent": "agreement-pill-notsent",
    "Sent": "agreement-pill-sent",
    "Signed": "agreement-pill-signed",
    "Declined": "agreement-pill-declined",
  };

  function defaultNextSteps(status) {
    if (status === "Signed") {
      return ["Your agreement is signed — no action needed here.", "Watch your email for final trip details as your date approaches."];
    }
    if (status === "Sent") {
      return ["Review and sign your agreement (see above).", "Return your group's forms and any outstanding participant paperwork.", "Reach out any time with questions before your date."];
    }
    if (status === "Declined") {
      return ["Contact your REEF educator to discuss next steps on your agreement."];
    }
    return ["Your REEF educator will send your agreement once program details are finalized.", "No action needed from you yet."];
  }

  // ---------------- FORMS & NEXT STEPS (agreement status + checklist + final reminders) ----------------
  function renderNextSteps(data) {
    const fr = data.finalReminders || {};
    const agreement = data.agreement || {};
    const status = agreement.status || "Not Sent";
    const pillClass = AGREEMENT_PILL_CLASS[status] || AGREEMENT_PILL_CLASS["Not Sent"];
    const steps = (data.nextSteps && data.nextSteps.items && data.nextSteps.items.length)
      ? data.nextSteps.items
      : defaultNextSteps(status);

    const agreementBlock = el("div", { class: "agreement-block" }, [
      el("div", { class: "agreement-status-row" }, [
        el("span", { class: "eyebrow" }, ["AGREEMENT STATUS"]),
        el("span", { class: "agreement-pill " + pillClass }, [status]),
        agreement.lastUpdated ? el("span", { class: "agreement-updated" }, [agreement.lastUpdated]) : null,
      ]),
      (status === "Sent" && agreement.zohoSignUrl)
        ? el("a", { class: "agreement-cta", href: agreement.zohoSignUrl, target: "_blank", rel: "noopener" }, ["Review & Sign Your Agreement →"])
        : null,
    ]);

    mount("next-steps", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("span", { class: "eyebrow" }, ["FORMS & NEXT STEPS"]),
          el("h2", {}, ["What happens next"]),
        ]),
        agreementBlock,
        el("div", { class: "next-steps-list" }, [
          el("span", { class: "eyebrow" }, ["NEXT STEPS"]),
          el("ul", {}, steps.map(function (line) { return el("li", {}, [line]); })),
        ]),
        el("div", { class: "section-head", style: "margin-top:32px;" }, [
          el("span", { class: "eyebrow" }, ["FINAL REMINDERS"]),
          el("h3", { style: "font-size:18px;" }, ["Before you arrive"]),
        ]),
        el("div", { class: "callout" }, [
          el("span", { class: "mark" }, ["”"]),
          data.flexNote || "Final activities and timing may adjust for weather, water conditions, vendor availability, and group readiness. Your REEF educator will communicate any day-of changes to your group leader directly.",
        ]),
        el("div", { class: "reminders-grid" }, [
          ["Arrival Time", fr.arrivalTime],
          ["Parking / Drop-off", fr.parking],
          ["REEF Contact", fr.reefContact],
          ["Questions Before Arrival", fr.questionsEmail || "info@REEF.org"],
        ].map(function (pair) {
          const has = pair[1] && String(pair[1]).trim().length;
          return el("div", { class: "field" }, [
            el("div", { class: "eyebrow" }, [pair[0]]),
            el("div", { class: "value" + (has ? "" : " placeholder") }, [placeholder(pair[1])]),
          ]);
        })),
      ]),
    ]));
  }

  // ================================================================
  // PROPOSAL MODE (docType: "proposal") — advanced six-section
  // customer proposal experience, ported from the Dropbox review
  // build (ocean-explorers-proposal-riverside-academy.html, Sprint
  // 2/3, "Customer Page Polish" sprint, Sept 2026). This replaces
  // the older, flatter "why it works / next steps" proposal
  // extras that used to bolt onto the confirmed-page template —
  // that page was never shipped to a real customer, so nothing
  // live depends on the old shape.
  //
  // This is a second, self-contained rendering mode: instead of
  // filling the mount points the pre-trip mode uses (#hero,
  // #welcome, #day-by-day, ...), it takes over the whole .page
  // element and builds its own sticky chapter-nav'd, six-section
  // shell — mirroring exactly how the original review build
  // worked (a single <main> populated entirely by script). It
  // never touches the pre-trip render functions above, and its
  // styles all live under .proposal-shell in styles.css so the
  // two modes can never bleed into each other visually even
  // though they share one stylesheet.
  //
  // PROPOSAL DATA SCHEMA (data.proposal, read only when
  // data.docType === "proposal"; data.meta.sampleFlag /
  // data.assetDepth are shared with pre-trip and reused as-is):
  // {
  //   meta: { bookingId, proposalVersion, proposalDate, programTypeLabel, programWord },
  //   group: { orgName, contactName, gradeLevel, students, chaperones },
  //   dates: { label, range },
  //   roadmap: { steps: [string,...], currentStep: number (1-based) },
  //   cta: {
  //     primaryText, primaryConfirmHeadline, primaryConfirmBody,
  //     secondaryText, changeFormLabel, changeConfirmHeadline, changeConfirmBody,
  //     contactEmail,
  //     responseWebhookUrl (optional): a Zapier "Catch Hook" URL the
  //       buttons POST a response payload to. Omit it and responses
  //       are only logged to the console + shown in an on-page
  //       confirmation state (matches the original review build).
  //       Wiring a real URL here is Implementation Plan item 5 (the
  //       new Zap replacing Airtable's broken native webhook) — a
  //       separate follow-up, not part of this rendering mode.
  //   },
  //   reefContact: { name, role, photo (url or null), welcomeLine, email, phone },
  //   welcome: { body: [string,...], signOff },
  //   glance: [ { k, v }, ... ],
  //   pillars: [ { title, text }, ... ],
  //   team: [ { name, role, bio }, ... ],
  //   days: [ same shape as the confirmed-page `days` schema above,
  //     plus an optional outcomesNote: string|null ],
  //   included: [ { title, items: [string,...] } ],
  //   notIncluded: [ string, ... ],
  //   photos (optional): { overview, experience, days, included, pricing, next }
  //     -- each a URL relative to this booking's own index.html
  //     (same convention as hero.imageUrl above). Any section
  //     without a photo falls back to a decorative gradient SVG,
  //     exactly as the original review build did — real REEF
  //     photography can be wired in later without changing this file.
  //   photoCredits (optional): { overview, experience, days, included, pricing, next },
  //   pricing: {
  //     tileRate: { label, num, unit }, tileChaperones: { label, num, unit },
  //     ratioNote, conditions: [string,...],
  //     estimatedTotal, estimatedTotalNote (may contain simple <strong> html),
  //     assumptions: [string,...], whatCouldChange: [string,...]
  //   }
  // }
  // ================================================================

  function renderAdvancedProposal(data) {
    const PD = data.proposal || {};
    PD.meta = PD.meta || {};
    PD.group = PD.group || {};
    PD.dates = PD.dates || {};
    PD.roadmap = PD.roadmap || { steps: [], currentStep: 1 };
    PD.cta = PD.cta || {};
    PD.reefContact = PD.reefContact || {};
    PD.welcome = PD.welcome || {};
    PD.glance = PD.glance || [];
    PD.pillars = PD.pillars || [];
    PD.team = PD.team || [];
    PD.days = PD.days || [];
    PD.included = PD.included || [];
    PD.notIncluded = PD.notIncluded || [];
    PD.photos = PD.photos || {};
    PD.photoCredits = PD.photoCredits || {};
    PD.pricing = PD.pricing || {};

    const programWord = PD.meta.programWord || "Expedition";
    const programTypeLabel = PD.meta.programTypeLabel || "Expedition";
    // Chapter 3's name follows the schedule format (2026-09-28): a rotation
    // proposal reads "Schedule & Rotations", a single-day program "Schedule",
    // a multi-day program "Day by Day". The pipeline sets it; this fallback
    // covers older data.js files.
    const scheduleLabel = PD.scheduleLabel || (PD.days.length > 1 ? "Day by Day" : "Schedule");

    // ---- decorative hero art: layered SVG, used as a fallback for any
    // section that doesn't have real photography yet. ----
    function heroSvg(kind) {
      const svgns = "http://www.w3.org/2000/svg";
      const defs = {
        overview: { g1: "#0F2A4E", g2: "#155E62", ray: "#1E7A73", bub: "#2C8F8A" },
        experience: { g1: "#0F2A4E", g2: "#1B3C74", ray: "#00A79D", bub: "#2C8F8A" },
        days: { g1: "#0B3350", g2: "#12506B", ray: "#1E8A83", bub: "#2FA79E" },
        included: { g1: "#12233D", g2: "#1B3C74", ray: "#3A6EA5", bub: "#2C8F8A" },
        pricing: { g1: "#0F2A4E", g2: "#1B3C74", ray: "#24408E", bub: "#3A6EA5" },
        next: { g1: "#0F2A4E", g2: "#0F6B63", ray: "#00A79D", bub: "#FFDD00" },
      };
      const c = defs[kind] || defs.overview;
      const uid = kind + Math.random().toString(36).slice(2, 7);
      const html = '' +
        '<svg viewBox="0 0 1200 420" preserveAspectRatio="xMidYMid slice" xmlns="' + svgns + '" role="presentation">' +
        '<defs>' +
          '<linearGradient id="bg' + uid + '" x1="0" y1="0" x2="1" y2="1">' +
            '<stop offset="0%" stop-color="' + c.g1 + '"/>' +
            '<stop offset="100%" stop-color="' + c.g2 + '"/>' +
          '</linearGradient>' +
          '<radialGradient id="sun' + uid + '" cx="18%" cy="0%" r="65%">' +
            '<stop offset="0%" stop-color="#ffffff" stop-opacity="0.16"/>' +
            '<stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>' +
          '</radialGradient>' +
        '</defs>' +
        '<rect width="1200" height="420" fill="url(#bg' + uid + ')"/>' +
        '<rect width="1200" height="420" fill="url(#sun' + uid + ')"/>' +
        '<g opacity="0.16" stroke="' + c.ray + '" stroke-width="26">' +
          '<line x1="60" y1="-40" x2="-60" y2="420"/>' +
          '<line x1="200" y1="-40" x2="60" y2="420"/>' +
          '<line x1="340" y1="-40" x2="180" y2="420"/>' +
        '</g>' +
        '<g fill="' + c.bub + '" opacity="0.5">' +
          '<circle cx="980" cy="90" r="7"/><circle cx="1020" cy="140" r="4"/>' +
          '<circle cx="1060" cy="70" r="5"/><circle cx="940" cy="150" r="4"/>' +
          '<circle cx="880" cy="60" r="6"/>' +
        '</g>' +
        '<g fill="' + c.g2 + '" opacity="0.9">' +
          '<path d="M0,420 L0,340 Q40,300 80,335 T160,330 Q190,290 230,325 T310,335 Q350,300 400,330 L400,420 Z"/>' +
          '<path d="M420,420 L420,360 Q470,320 520,350 T620,345 Q660,310 710,340 L760,420 Z" opacity="0.85"/>' +
        '</g>' +
        '<g fill="' + c.ray + '" opacity="0.55">' +
          '<ellipse cx="1080" cy="380" rx="120" ry="60"/>' +
          '<ellipse cx="150" cy="400" rx="180" ry="55"/>' +
        '</g>' +
        (kind === "next" ? '<circle cx="1000" cy="120" r="46" fill="#FFDD00" opacity="0.85"/>' : '') +
        '</svg>';
      return el("div", { class: "hero-art", html: html });
    }

    // Section-specific alt text for real hero photography (accessibility
    // fix, QA walkthrough 2026-09-09). The decorative SVG fallback stays
    // role="presentation" with no alt needed -- it's purely ornamental.
    const HERO_ALT_TEXT = {
      overview: "REEF Ocean Explorers program overview",
      experience: "Students taking part in a REEF Ocean Explorers activity",
      days: "A REEF Ocean Explorers field activity in the Florida Keys",
      included: "REEF Ocean Explorers Expedition activities and gear",
      pricing: "REEF Ocean Exploration Center, Key Largo",
      next: "The Florida Keys coastline near REEF's Ocean Exploration Center",
    };

    // ---- real-photo hero: an <img> + scrim for text legibility. ----
    function heroPhoto(uri, kind) {
      return el("div", { class: "hero-art has-photo" }, [
        el("img", { class: "hero-photo", src: uri, alt: HERO_ALT_TEXT[kind] || "REEF Ocean Explorers" }),
        el("div", { class: "hero-scrim" }),
      ]);
    }

    function heroBlock(kind, photoUri, credit) {
      const art = photoUri ? heroPhoto(photoUri, kind) : heroSvg(kind);
      const wrap = el("div", { class: "hero" }, [art]);
      if (credit) wrap.appendChild(el("div", { class: "hero-credit" }, [credit]));
      return wrap;
    }

    function bottomNav(prevLabel, prevId, nextLabel, nextId) {
      const wrap = el("div", { class: "section-nav" });
      if (prevId) {
        const b = el("button", { class: "nav-prev", "data-goto": prevId }, [
          el("span", { class: "lbl" }, ["← Previous"]),
          el("span", { class: "name" }, [prevLabel]),
        ]);
        wrap.appendChild(b);
      } else {
        wrap.appendChild(el("span", { class: "nav-spacer" }, []));
      }
      if (nextId) {
        const b = el("button", { class: "nav-next", "data-goto": nextId }, [
          el("span", { class: "lbl" }, ["Next"]),
          el("span", { class: "name" }, [nextLabel + " →"]),
        ]);
        wrap.appendChild(b);
      }
      return wrap;
    }

    function roadmap() {
      // QA walkthrough (2026-09-09): this booking-progress tracker could be
      // confused with the six-chapter proposal navigation in the topbar.
      // The "YOUR BOOKING STATUS" badge names what this widget actually is
      // (booking-stage tracker, not a table of contents); the badge plus
      // the card's own background/border already visually set it apart
      // from the chapter nav — see .roadmap-badge in styles.css.
      const box = el("div", { class: "roadmap" }, [
        el("span", { class: "roadmap-badge" }, ["YOUR BOOKING STATUS"]),
        el("div", { class: "roadmap-title" }, ["Where You Are In The Process"]),
      ]);
      const stepsWrap = el("div", { class: "roadmap-steps" });
      PD.roadmap.steps.forEach(function (label, i) {
        const n = i + 1;
        const cls = "rstep" + (n < PD.roadmap.currentStep ? " is-done" : "") + (n === PD.roadmap.currentStep ? " is-current" : "");
        const dot = el("div", { class: "rstep-dot" }, [n < PD.roadmap.currentStep ? "✓" : String(n)]);
        const children = [el("div", { class: "rstep-line" }), dot, el("div", { class: "rstep-label" }, [label])];
        if (n === PD.roadmap.currentStep) children.push(el("div", { class: "rstep-here" }, ["You Are Here"]));
        stepsWrap.appendChild(el("div", { class: cls }, children));
      });
      box.appendChild(stepsWrap);
      return box;
    }

    /* ------------------------------------------------------------------
       CTA MODULE — one primary action ("Ready to Move Forward") and one
       secondary path ("Need to adjust something?" -> an inline "Request
       a Change" form). State is shared across both CTA module instances
       on the page (Overview + Next Steps) so a customer only submits
       once. See PD.cta.responseWebhookUrl above for the write-back note.
       ------------------------------------------------------------------ */
    let ctaState = { status: "pending", payload: null }; // pending | ready | change_requested
    const ctaRenderers = [];

    function fmtTimestamp(iso) {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
        " at " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    }

    function submitProposalResponse(type, message) {
      const payload = {
        bookingId: PD.meta.bookingId,
        orgName: PD.group.orgName,
        contactName: PD.group.contactName,
        proposalVersion: PD.meta.proposalVersion,
        respondedAt: new Date().toISOString(),
        response: type, // "ready_to_proceed" | "change_requested"
        message: message || null,
      };
      if (PD.cta.responseWebhookUrl) {
        // Implementation Plan item 5: point this at the new Zapier "Catch
        // Hook" trigger (not Airtable's broken native webhook). Fire-and
        // forget — the on-page confirmation below doesn't wait on it, so
        // a slow/unreachable network doesn't strand the customer.
        try {
          fetch(PD.cta.responseWebhookUrl, {
            method: "POST",
            body: JSON.stringify(payload),
            mode: "cors",
            keepalive: true,
          }).catch(function (err) { console.error("[REEF proposal response] webhook POST failed", err); });
        } catch (err) {
          console.error("[REEF proposal response] webhook POST failed", err);
        }
      } else {
        console.log("[REEF proposal response — no responseWebhookUrl configured yet, not sent anywhere]", payload);
      }
      ctaState = { status: type === "ready_to_proceed" ? "ready" : "change_requested", payload: payload };
      ctaRenderers.forEach(function (render) { render(); });
    }

    // What the customer is approving -- the same facts as the rest of the
    // proposal, restated in one place right before the approval click
    // (2026-09-28 copy review). Built by the pipeline as PD.confirmSummary.
    function confirmSummaryList(cls) {
      const items = PD.confirmSummary || [];
      if (!items.length) return null;
      return el("dl", { class: "confirm-summary " + (cls || "") }, items.map(function (it) {
        return el("div", { class: "cs-row" }, [el("dt", {}, [it.k]), el("dd", {}, [it.v])]);
      }));
    }

    function ctaModule() {
      const root = el("div", { class: "cta-module" });
      let formOpen = false;
      let confirmingReady = false;

      function pendingView() {
        const btnReady = el("button", { class: "btn btn-primary" }, [(PD.cta.primaryText || "Looks Good — Prepare My Contract") + "\u00a0→"]);
        btnReady.addEventListener("click", function () { confirmingReady = true; render(); });
        const btnChange = el("button", { class: "cta-secondary-link" }, [PD.cta.secondaryText || "Request a Change"]);
        btnChange.addEventListener("click", function () { formOpen = true; render(); });
        return el("div", {}, [
          el("span", { class: "eyebrow on-dark" }, ["YOUR NEXT STEP"]),
          el("h3", {}, ["Review your proposal for " + placeholder(PD.group.orgName, "your group")]),
          el("p", {}, ["When the schedule, group size, inclusions, and pricing look right, approve the proposal and REEF will prepare your contract. Approving doesn't sign anything or commit a payment. If something needs to change, send us a request instead."]),
          el("div", { class: "cta-row" }, [btnReady, btnChange]),
        ]);
      }

      // QA walkthrough (2026-09-09): "Ready to Move Forward" jumped straight
      // to the success state, so even though the copy says it doesn't sign
      // anything, the button itself felt like a bigger commitment than it
      // is. This interstitial makes the actual consequence explicit and
      // requires a second, deliberate click before anything is submitted.
      function confirmReadyView() {
        const btnConfirm = el("button", { class: "btn btn-primary" }, [(PD.cta.confirmButtonText || "Approve Proposal") + "\u00a0→"]);
        btnConfirm.addEventListener("click", function () { submitProposalResponse("ready_to_proceed", null); });
        const btnBack = el("button", { class: "cta-secondary-link" }, ["Not yet, take me back"]);
        btnBack.addEventListener("click", function () { confirmingReady = false; render(); });
        return el("div", {}, [
          el("span", { class: "eyebrow on-dark" }, ["BEFORE YOU APPROVE"]),
          el("h3", {}, ["You're approving this program"]),
          confirmSummaryList("cta-summary"),
          el("p", {}, ["After you approve, REEF will prepare your contract and confirm any remaining details with you. Approving doesn't sign anything or commit a payment."]),
          el("div", { class: "cta-row" }, [btnConfirm, btnBack]),
        ]);
      }

      function changeFormView() {
        const fieldId = "cta-change-request-" + Math.random().toString(36).slice(2, 8);
        const label = el("label", { class: "cta-textarea-label", for: fieldId }, [PD.cta.changeFormLabel || "Tell us about any requested changes to dates, activities, timing, group size, transportation, meals, accessibility needs, or program content."]);
        const ta = el("textarea", { id: fieldId, class: "cta-textarea", rows: "3" });
        const submitBtn = el("button", { class: "btn btn-primary", disabled: "disabled" }, ["Send Request"]);
        // QA walkthrough (2026-09-09): the textarea had no real label (only
        // placeholder text, which disappears once typing starts) and
        // Send Request was clickable on an empty field. Both fixed here;
        // the button only enables once there's real (non-whitespace) text.
        ta.addEventListener("input", function () {
          if (ta.value.trim().length) submitBtn.removeAttribute("disabled");
          else submitBtn.setAttribute("disabled", "disabled");
        });
        submitBtn.addEventListener("click", function () {
          if (!ta.value.trim().length) return;
          submitProposalResponse("change_requested", ta.value.trim());
        });
        const cancelBtn = el("button", { class: "cta-secondary-link" }, ["Never mind, take me back"]);
        cancelBtn.addEventListener("click", function () { formOpen = false; render(); });
        return el("div", {}, [
          el("span", { class: "eyebrow on-dark" }, ["REQUEST A CHANGE"]),
          el("h3", {}, ["What should we change?"]),
          el("p", {}, ["Your REEF contact will review your request, follow up by email, and send a revised proposal if the schedule or price changes."]),
          label,
          ta,
          el("div", { class: "cta-row" }, [submitBtn, cancelBtn]),
          el("p", { class: "cta-fine", style: "margin-top:10px;" }, [PD.cta.changeResponseNote || "A REEF team member typically follows up by email within 1–2 business days."]),
        ]);
      }

      function readyConfirmView() {
        return el("div", {}, [
          el("span", { class: "eyebrow on-dark" }, ["✓ PROPOSAL APPROVED"]),
          el("h3", {}, [PD.cta.primaryConfirmHeadline || "Thank you — your proposal is approved."]),
          el("p", {}, [PD.cta.primaryConfirmBody || "REEF will prepare your contract and confirm any remaining details with you by email."]),
          el("p", { class: "cta-fine" }, ["Logged for " + placeholder(PD.group.orgName, "your group") + " · " + fmtTimestamp(ctaState.payload.respondedAt)]),
        ]);
      }

      function changeConfirmedView() {
        const children = [
          el("span", { class: "eyebrow on-dark" }, ["✓ REQUEST SENT"]),
          el("h3", {}, [PD.cta.changeConfirmHeadline || "Thank you — your change request is on its way."]),
          el("p", {}, [PD.cta.changeConfirmBody || "Your REEF contact will follow up by email and send a revised proposal if anything changes."]),
        ];
        if (ctaState.payload && ctaState.payload.message) {
          children.push(el("p", { class: "cta-fine" }, ["Your note: “" + ctaState.payload.message + "”"]));
        }
        return el("div", {}, children);
      }

      function render() {
        root.innerHTML = "";
        if (ctaState.status === "ready") root.appendChild(readyConfirmView());
        else if (ctaState.status === "change_requested") root.appendChild(changeConfirmedView());
        else if (formOpen) root.appendChild(changeFormView());
        else if (confirmingReady) root.appendChild(confirmReadyView());
        else root.appendChild(pendingView());
      }

      render();
      ctaRenderers.push(render);
      return root;
    }

    // ---------------- SECTION BUILDERS ----------------
    function buildOverview() {
      const s = el("section", { id: "sec-overview", class: "page-section", "data-title": "Overview" });
      s.appendChild(heroBlock("overview", PD.photos.overview, PD.photoCredits.overview));
      s.querySelector(".hero").appendChild(el("div", { class: "hero-inner container" }, [
        el("span", { class: "hero-eyebrow" }, ["A PROPOSAL FOR " + placeholder(PD.group.orgName, "YOUR GROUP").toUpperCase()]),
        el("h1", {}, ["Florida Keys Ocean Explorers " + programTypeLabel]),
        // 2026-09-28 copy review: one concrete sentence describing THIS
        // program (built by the pipeline, or supplied per booking) instead
        // of a generic "built around your group's goals" line.
        el("p", { class: "lede" }, [PD.summary || ("A " + (PD.days.length === 1 ? "one-day" : PD.days.length + "-day") + " " + programWord + " prepared for " + placeholder(PD.group.orgName, "your group") + ".")]),
        el("div", { class: "hero-chips" }, [
          ["Group", PD.group.orgName],
          [PD.days.length > 1 ? "Proposed Dates" : "Proposed Date", PD.dates.range],
          [PD.group.contactLabel || "Group Contact", PD.group.contactLine || PD.group.contactName || PD.group.gradeLevel],
          ["Group Size", (PD.group.students || 0) + " students + " + (PD.group.chaperones || 0) + " chaperones"],
        ].map(function (pair) { return el("div", { class: "hero-chip" }, [el("div", { class: "k" }, [pair[0]]), el("div", { class: "v" }, [placeholder(pair[1])])]); })),
      ]));
      s.appendChild(el("div", { class: "container block" }, [roadmap()]));
      s.appendChild(el("div", { class: "container block" }, [ctaModule()]));
      s.appendChild(el("div", { class: "container block" }, [
        el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["WELCOME"]), el("h2", {}, ["A note from your REEF contact"])]),
        el("div", { class: "prose" }, PD.welcome.body.map(function (p) { return el("p", {}, [p]); }).concat(PD.welcome.signOff ? [el("p", { class: "signoff" }, [PD.welcome.signOff])] : [])),
      ]));
      s.appendChild(el("div", { class: "container block" }, [
        el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["AT A GLANCE"]), el("h2", {}, ["Your " + programWord + ", at a glance"])]),
        el("div", { class: "glance-grid" }, PD.glance.map(function (g) {
          return el("div", { class: "glance-cell" + (g.wide ? " is-wide" : "") }, [el("div", { class: "k" }, [g.k]), el("div", { class: "v" }, [g.v])]);
        })),
      ]));
      s.appendChild(el("div", { class: "container block" }, [
        el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["YOUR REEF CONTACT"])]),
        el("div", { class: "contact-card" }, [
          el("div", { class: "contact-avatar" }, PD.reefContact.photo
            ? [el("img", { src: PD.reefContact.photo, alt: PD.reefContact.name || "" })]
            : [(PD.reefContact.name || "REEF").split(" ").map(function (w) { return w[0]; }).join("")]),
          el("div", { class: "contact-body" }, [
            el("div", { class: "contact-name" }, [placeholder(PD.reefContact.name, "REEF Team")]),
            el("div", { class: "contact-role" }, [PD.reefContact.role || ""]),
            // Skip the blurb when it would repeat the welcome note verbatim
            // (2026-09-28: the same sentence appeared twice on Overview).
            (PD.reefContact.welcomeLine && (PD.welcome.body || []).indexOf(PD.reefContact.welcomeLine) === -1)
              ? el("div", { class: "contact-blurb" }, [PD.reefContact.welcomeLine]) : null,
            el("div", { class: "contact-links" }, [
              el("a", { href: "mailto:" + (PD.reefContact.email || "explorers@REEF.org") }, [PD.reefContact.email || "explorers@REEF.org"]),
              el("span", { style: "color:var(--p-slate-soft)" }, [PD.reefContact.phone || ""]),
            ]),
          ]),
        ]),
      ]));
      s.appendChild(el("div", { class: "container" }, [bottomNav(null, null, "Your Experience", "sec-experience")]));
      return s;
    }

    function buildExperience() {
      const s = el("section", { id: "sec-experience", class: "page-section", "data-title": "Your Experience" });
      s.appendChild(heroBlock("experience", PD.photos.experience, PD.photoCredits.experience));
      s.querySelector(".hero").appendChild(el("div", { class: "hero-inner container" }, [
        el("span", { class: "hero-eyebrow" }, ["YOUR EXPERIENCE"]),
        el("h1", {}, ["Hands-on marine science, led by REEF educators"]),
        el("p", { class: "lede" }, ["How your students will take part in real ocean conservation work during this " + programWord + ", and why it matters beyond the day itself."]),
      ]));
      s.appendChild(el("div", { class: "container block" }, [
        el("div", { class: "card-grid cols-2" }, PD.pillars.map(function (p) {
          return el("div", { class: "pillar-card" }, [el("h4", {}, [p.title]), el("p", {}, [p.text])]);
        })),
      ]));
      if (PD.team.length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["THE REEF TEAM"]), el("h2", {}, ["Who your students will learn with"])]),
          el("div", { class: "team-note" }, ["REEF assigns specific educators closer to your date. These are the roles that support every program like yours."]),
          el("div", { class: "team-grid" }, PD.team.map(function (t) {
            // QA walkthrough (2026-09-09): every team card used the same
            // generic "◍" glyph, which read as impersonal. Real headshots
            // aren't available yet (no Airtable field backs them), so this
            // swaps in per-person initials -- a small change, but distinct
            // per card rather than identical across all of them.
            const initials = (t.name || "REEF").split(" ").filter(function (w) { return w.length; })
              .map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase();
            return el("div", { class: "team-card" }, [
              el("div", { class: "team-avatar" }, [initials]),
              el("div", { class: "name" }, [t.name]), el("div", { class: "role" }, [t.role]), el("div", { class: "bio" }, [t.bio]),
            ]);
          })),
        ]));
      }
      s.appendChild(el("div", { class: "container" }, [bottomNav("Overview", "sec-overview", scheduleLabel, "sec-days")]));
      return s;
    }

    function daySwatchSvg(dayNumber) {
      const color = dayNumber === 1 ? "#00A79D" : "#3A6EA5";
      return '<svg viewBox="0 0 44 44" width="44" height="44"><rect width="44" height="44" rx="9" fill="' + color + '" opacity="0.35"/><circle cx="16" cy="18" r="5" fill="#fff" opacity="0.8"/><circle cx="28" cy="26" r="7" fill="#fff" opacity="0.55"/></svg>';
    }

    function dayCard(day) {
      const blocks = (day.blocks || []).map(function (b) {
        return el("div", { class: "time-block" }, [
          el("div", { class: "time mono" }, [b.time || ""]),
          el("div", {}, [b.tag ? el("span", { class: "tag" }, [b.tag]) : null, el("h4", {}, [b.title || ""]), el("p", { class: "desc" }, [b.description || ""])]),
        ]);
      });
      return el("div", { class: "day-card" }, [
        el("div", { class: "day-card-head" }, [
          el("div", { class: "day-swatch", html: daySwatchSvg(day.dayNumber) }),
          el("div", {}, [
            el("div", { class: "of" }, ["DAY " + day.dayNumber + " OF " + (day.totalDays || day.dayNumber)]),
            el("h3", {}, [day.title || ""]),
            day.theme ? el("div", { class: "theme" }, [day.theme]) : null,
          ]),
        ]),
        el("div", { class: "day-body" }, blocks.concat([
          (day.studentsWill || []).length ? el("div", { class: "outcomes-box" }, [
            el("span", { class: "eyebrow" }, ["STUDENTS WILL…"]),
            el("ul", {}, day.studentsWill.map(function (line) { return el("li", {}, [line]); })),
            day.outcomesNote ? el("div", { class: "outcomes-note" }, [day.outcomesNote]) : null,
          ]) : null,
        ])),
      ]);
    }

    // ================================================================
    // ROTATION SCHEDULE (2026-09-28) -- reusable concurrent-cohort
    // component, shown when PD.scheduleFormat === "rotation". Answers
    // "who is where, and when": cohorts are rows, time runs left to
    // right, each activity is a labeled cell spanning its real duration,
    // and gaps between a cohort's activities show as transition time.
    // On narrow screens the same grid is transposed (time runs down,
    // cohorts across) so cohort-by-time relationships survive on a
    // phone instead of collapsing into disconnected cards. Activity
    // descriptions stay below the matrix. Data shape: see ROTATION
    // SCHEMA in pipeline/generate_booking_package.py.
    // ================================================================
    function tmin(hhmm) { const p = String(hhmm).split(":"); return (+p[0]) * 60 + (+p[1]); }
    function clockLabel(m, withSuffix) {
      const h = Math.floor(m / 60), mm = m % 60;
      const h12 = h % 12 || 12;
      return h12 + ":" + String(mm).padStart(2, "0") + (withSuffix ? (h < 12 ? " AM" : " PM") : "");
    }
    function rangeLabel(s, e) {
      const sa = s < 720 ? "AM" : "PM", ea = e < 720 ? "AM" : "PM";
      return sa === ea ? clockLabel(s) + "–" + clockLabel(e, true) : clockLabel(s, true) + "–" + clockLabel(e, true);
    }

    function rotationModel(rot) {
      const slot = rot.slotMinutes || 15;
      const start = tmin(rot.startTime), end = tmin(rot.endTime);
      const stations = {};
      (rot.stations || []).forEach(function (st, i) {
        stations[st.id] = Object.assign({ color: i % 6 }, st);
      });
      const cohorts = (rot.cohorts || []).map(function (c) {
        const items = [];
        (rot.assignments || []).forEach(function (a) {
          if (a.cohort === c.id) items.push({ s: tmin(a.start), e: tmin(a.end), st: stations[a.station] });
        });
        (rot.shared || []).forEach(function (a) {
          items.push({ s: tmin(a.start), e: tmin(a.end), st: stations[a.station], shared: true });
        });
        items.sort(function (x, y) { return x.s - y.s; });
        // Fill gaps with transition time so the row always reads start-to-end.
        const filled = [];
        let cursor = start;
        items.forEach(function (it) {
          if (it.s > cursor) filled.push({ s: cursor, e: it.s, gap: true });
          filled.push(it);
          cursor = Math.max(cursor, it.e);
        });
        if (cursor < end) filled.push({ s: cursor, e: end, gap: true });
        return { c: c, items: filled };
      });
      const span = end - start;
      const tickStep = span > 360 ? 60 : 30;
      return { slot: slot, start: start, end: end, n: span / slot, stations: stations, cohorts: cohorts, tickStep: tickStep };
    }

    function cohortSizeText(rot, c) {
      if (c.size) return c.size + " students";
      return rot.cohortSizeLabel || "";
    }

    function rotationCellContent(it, compact) {
      if (it.gap) return [el("span", { class: "rc-gap-label" }, [(it.e - it.s) >= 30 ? "Transition" : ""])];
      const name = compact ? (it.st.short || it.st.name) : ((it.e - it.s) >= 60 ? it.st.name : (it.st.short || it.st.name));
      return [
        el("span", { class: "rc-name" }, [name]),
        el("span", { class: "rc-time mono" }, [rangeLabel(it.s, it.e)]),
        (!compact && it.st.location && (it.e - it.s) >= 60) ? el("span", { class: "rc-loc" }, [it.st.location]) : null,
      ];
    }

    function rotationDesktop(rot, M) {
      const hasDep = !!rot.departure;
      const cols = "var(--rot-label) repeat(" + M.n + ", minmax(0,1fr))" + (hasDep ? " var(--rot-dep)" : "");
      const grid = el("div", { class: "rot-grid rot-desktop", style: "grid-template-columns:" + cols + ";", role: "img",
        "aria-label": "Rotation schedule: " + M.cohorts.length + " cohorts from " + clockLabel(M.start, true) + " to " + clockLabel(M.end, true) + ". A text version follows." });
      grid.appendChild(el("div", { class: "rot-corner", style: "grid-row:1;grid-column:1;" }, ["Cohort"]));
      for (let t = M.start; t < M.end; t += M.tickStep) {
        const i = (t - M.start) / M.slot;
        const w = Math.min(M.tickStep, M.end - t) / M.slot;
        grid.appendChild(el("div", { class: "rot-tick", style: "grid-row:1;grid-column:" + (i + 2) + " / span " + w + ";" },
          [clockLabel(t, t === M.start || t === 720)]));
      }
      if (hasDep) grid.appendChild(el("div", { class: "rot-tick rot-tick-dep", style: "grid-row:1;grid-column:" + (M.n + 2) + ";" }, [clockLabel(tmin(rot.departure.time), true)]));
      M.cohorts.forEach(function (row, r) {
        const gr = r + 2;
        grid.appendChild(el("div", { class: "rot-rowlabel", style: "grid-row:" + gr + ";grid-column:1;" }, [
          el("span", { class: "rl-name" }, [row.c.label]),
          cohortSizeText(rot, row.c) ? el("span", { class: "rl-size" }, [cohortSizeText(rot, row.c)]) : null,
        ]));
        row.items.forEach(function (it) {
          const a = (it.s - M.start) / M.slot + 2, b = (it.e - M.start) / M.slot + 2;
          const cls = (it.gap ? "rot-cell rot-gap" : "rot-cell rot-c" + (it.st.color % 6)) + ((it.e - it.s) <= 30 ? " is-narrow" : "");
          grid.appendChild(el("div", { class: cls, style: "grid-row:" + gr + ";grid-column:" + a + " / " + b + ";" }, rotationCellContent(it, (it.e - it.s) <= 30)));
        });
      });
      if (hasDep) {
        grid.appendChild(el("div", { class: "rot-dep", style: "grid-row:2 / span " + M.cohorts.length + ";grid-column:" + (M.n + 2) + ";" }, [
          el("span", { class: "rc-name" }, [rot.departure.label || "Departure"]),
        ]));
      }
      return grid;
    }

    function rotationMobile(rot, M) {
      const hasDep = !!rot.departure;
      const nC = M.cohorts.length;
      const rows = "auto repeat(" + M.n + ", var(--rot-slot-h))" + (hasDep ? " auto" : "");
      const grid = el("div", { class: "rot-grid rot-mobile", style: "grid-template-columns:var(--rot-time) repeat(" + nC + ", minmax(0,1fr));grid-template-rows:" + rows + ";", role: "img",
        "aria-label": "Rotation schedule, time runs down and cohorts run across. A text version follows." });
      grid.appendChild(el("div", { class: "rot-corner", style: "grid-row:1;grid-column:1;" }, ["Time"]));
      M.cohorts.forEach(function (row, ci) {
        grid.appendChild(el("div", { class: "rot-colhead", style: "grid-row:1;grid-column:" + (ci + 2) + ";" }, [
          el("span", { class: "rl-name" }, [row.c.label.replace(/^Cohort\s+/i, "")]),
          el("span", { class: "rl-kicker" }, [/^Cohort\s+/i.test(row.c.label) ? "Cohort" : ""]),
        ]));
      });
      for (let t = M.start; t < M.end; t += M.tickStep) {
        const i = (t - M.start) / M.slot;
        const h = Math.min(M.tickStep, M.end - t) / M.slot;
        grid.appendChild(el("div", { class: "rot-vtick mono", style: "grid-column:1;grid-row:" + (i + 2) + " / span " + h + ";" }, [clockLabel(t, t === M.start || t === 720)]));
      }
      M.cohorts.forEach(function (row, ci) {
        row.items.forEach(function (it) {
          const a = (it.s - M.start) / M.slot + 2, b = (it.e - M.start) / M.slot + 2;
          const cls = it.gap ? "rot-cell rot-gap" : "rot-cell rot-c" + (it.st.color % 6);
          grid.appendChild(el("div", { class: cls, style: "grid-column:" + (ci + 2) + ";grid-row:" + a + " / " + b + ";" }, rotationCellContent(it, true)));
        });
      });
      if (hasDep) {
        grid.appendChild(el("div", { class: "rot-vtick mono", style: "grid-column:1;grid-row:" + (M.n + 2) + ";" }, [clockLabel(tmin(rot.departure.time), true)]));
        grid.appendChild(el("div", { class: "rot-dep rot-dep-row", style: "grid-column:2 / span " + nC + ";grid-row:" + (M.n + 2) + ";" }, [
          el("span", { class: "rc-name" }, [rot.departure.label || "Departure"]),
        ]));
      }
      return grid;
    }

    function rotationLegend(rot, M) {
      return el("ul", { class: "rot-legend", "aria-label": "Activities and locations" }, (rot.stations || []).map(function (st) {
        const s = M.stations[st.id];
        return el("li", {}, [
          el("span", { class: "rot-swatch rot-c" + (s.color % 6) }),
          el("span", { class: "lg-name" }, [s.name]),
          s.location ? el("span", { class: "lg-loc" }, [s.location]) : null,
        ]);
      }));
    }

    function rotationTextList(rot, M) {
      const details = el("details", { class: "rot-list" }, [el("summary", {}, ["View the schedule as a list by cohort"])]);
      const wrap = el("div", { class: "rot-list-grid" });
      M.cohorts.forEach(function (row) {
        wrap.appendChild(el("div", { class: "rot-list-col" }, [
          el("h4", {}, [row.c.label + (cohortSizeText(rot, row.c) ? " · " + cohortSizeText(rot, row.c) : "")]),
          el("ul", {}, row.items.filter(function (it) { return !it.gap; }).map(function (it) {
            return el("li", {}, [el("span", { class: "mono" }, [rangeLabel(it.s, it.e)]), " ", it.st.name + (it.st.location ? " (" + it.st.location + ")" : "")]);
          }).concat(rot.departure ? [el("li", {}, [el("span", { class: "mono" }, [clockLabel(tmin(rot.departure.time), true)]), " ", rot.departure.label || "Departure"])] : [])),
        ]));
      });
      details.appendChild(wrap);
      return details;
    }

    function rotationSchedule(rot) {
      const M = rotationModel(rot);
      return el("div", { class: "rot-wrap" }, [
        el("div", { class: "rot-frame" }, [rotationDesktop(rot, M), rotationMobile(rot, M)]),
        rotationLegend(rot, M),
        rot.departure && rot.departure.note ? el("p", { class: "rot-note rot-note-strong" }, [rot.departure.note]) : null,
        (rot.notes || []).length ? el("ul", { class: "rot-notes" }, rot.notes.map(function (n) { return el("li", {}, [n]); })) : null,
        rotationTextList(rot, M),
      ]);
    }

    // Activity detail cards below the matrix: what students experience and
    // learn, with WHEN derived from the rotation data (never hand-typed, so
    // it can't disagree with the matrix).
    function stationCards(day) {
      const cards = (day.blocks || []).map(function (b) {
        return el("div", { class: "station-card" + (b.color !== undefined && b.color !== null ? " rot-edge-c" + (b.color % 6) : "") }, [
          b.tag ? el("span", { class: "tag" }, [b.tag]) : null,
          el("h4", {}, [b.title || ""]),
          b.when ? el("div", { class: "sc-when mono" }, [b.when]) : (b.time ? el("div", { class: "sc-when mono" }, [b.time]) : null),
          b.location ? el("div", { class: "sc-loc" }, [b.location]) : null,
          el("p", { class: "desc" }, [b.description || ""]),
        ]);
      });
      return el("div", { class: "station-grid" }, cards);
    }

    function outcomesBox(day) {
      return (day.studentsWill || []).length ? el("div", { class: "outcomes-box standalone" }, [
        el("span", { class: "eyebrow" }, ["STUDENTS WILL…"]),
        el("ul", {}, day.studentsWill.map(function (line) { return el("li", {}, [line]); })),
        day.outcomesNote ? el("div", { class: "outcomes-note" }, [day.outcomesNote]) : null,
      ]) : null;
    }

    function buildDays() {
      const fmt = PD.scheduleFormat || "standard";
      const s = el("section", { id: "sec-days", class: "page-section", "data-title": scheduleLabel });
      s.appendChild(heroBlock("days", PD.photos.days, PD.photoCredits.days));
      let h1, lede;
      if (fmt === "rotation" && PD.rotation) {
        h1 = PD.rotation.heading || "One Coordinated Schedule";
        lede = "Where each cohort will be, and when" + (PD.hours ? ", from " + PD.rotation.startLabel + " to " + PD.rotation.endLabel : "") + ".";
      } else if (fmt === "pending") {
        h1 = "Your schedule is being finalized";
        lede = "The experiences below are part of your program. Exact times will follow.";
      } else {
        h1 = (PD.days.length === 1 ? "One day" : PD.days.length + " days") + ", one Florida Keys " + programWord;
        lede = "What your students will do, and when.";
      }
      s.querySelector(".hero").appendChild(el("div", { class: "hero-inner container" }, [
        el("span", { class: "hero-eyebrow" }, [scheduleLabel.toUpperCase()]),
        el("h1", {}, [h1]),
        el("p", { class: "lede" }, [lede]),
      ]));
      if (fmt === "rotation" && PD.rotation) {
        s.appendChild(el("div", { class: "container block" }, [
          PD.rotation.intro ? el("p", { class: "rot-intro" }, [PD.rotation.intro]) : null,
          rotationSchedule(PD.rotation),
        ]));
        PD.days.forEach(function (day) {
          s.appendChild(el("div", { class: "container block" }, [
            el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["THE EXPERIENCES"]), el("h2", {}, ["What students will do at each stop"])]),
            stationCards(day),
            outcomesBox(day),
          ]));
        });
      } else if (fmt === "pending") {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "pending-panel" }, [
            el("span", { class: "eyebrow" }, ["SCHEDULE COMING SOON"]),
            el("p", {}, [PD.pendingNote || "Your detailed schedule is still being finalized. Your REEF contact will share exact times before your contract is prepared."]),
          ]),
        ].concat(PD.days.map(function (day) { return el("div", { style: "margin-top:20px;" }, [stationCards(day), outcomesBox(day)]); }))));
      } else {
        s.appendChild(el("div", { class: "container block" }, PD.days.map(dayCard)));
      }
      s.appendChild(el("div", { class: "container" }, [bottomNav("Your Experience", "sec-experience", "What's Included", "sec-included")]));
      return s;
    }

    function buildIncluded() {
      const s = el("section", { id: "sec-included", class: "page-section", "data-title": "What's Included" });
      s.appendChild(heroBlock("included", PD.photos.included, PD.photoCredits.included));
      s.querySelector(".hero").appendChild(el("div", { class: "hero-inner container" }, [
        el("span", { class: "hero-eyebrow" }, ["WHAT'S INCLUDED"]),
        el("h1", {}, ["What's included, and what your group brings"]),
        el("p", { class: "lede" }, ["What REEF provides, what your group arranges, and anything that isn't part of this price."]),
      ]));
      const cards = PD.included.filter(function (g) { return (g.items || []).length; }).map(function (g) {
        return el("div", { class: "included-card" }, [
          el("h4", {}, [el("span", { class: "dot" }), g.title]),
          el("ul", {}, (g.items || []).map(function (i) { return el("li", {}, [i]); })),
        ]);
      });
      if (PD.notIncluded.length) {
        cards.push(el("div", { class: "included-card not-included" }, [
          el("h4", {}, [el("span", { class: "dot" }), "Not included — arranged by your group"]),
          el("ul", {}, PD.notIncluded.map(function (i) { return el("li", {}, [i]); })),
        ]));
      }
      if ((PD.optional || []).length) {
        cards.push(el("div", { class: "included-card optional-card" }, [
          el("h4", {}, [el("span", { class: "dot" }), "Optional — not included in this price"]),
          el("ul", {}, PD.optional.map(function (i) { return el("li", {}, [i]); })),
        ]));
      }
      if (!cards.length) {
        cards.push(el("div", { class: "included-card" }, [el("p", {}, ["Your REEF contact will confirm exactly what's included with your final proposal."])]));
      }
      s.appendChild(el("div", { class: "container block" }, [el("div", { class: "included-grid" }, cards)]));
      s.appendChild(el("div", { class: "container" }, [bottomNav(scheduleLabel, "sec-days", "Pricing & Details", "sec-pricing")]));
      return s;
    }

    function buildPricing() {
      const pr = PD.pricing;
      const s = el("section", { id: "sec-pricing", class: "page-section", "data-title": "Pricing & Details" });
      s.appendChild(heroBlock("pricing", PD.photos.pricing, PD.photoCredits.pricing));
      s.querySelector(".hero").appendChild(el("div", { class: "hero-inner container" }, [
        el("span", { class: "hero-eyebrow" }, ["PRICING & DETAILS"]),
        el("h1", {}, ["Your estimated total"]),
        el("p", { class: "lede" }, ["What your price includes, what it's based on, and what would change it."]),
      ]));
      const tiles = [pr.tileTotal, pr.tileRate, pr.tileChaperones].filter(Boolean);
      if (tiles.length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "price-tiles cols-" + tiles.length }, tiles.map(function (tile, i) {
            return el("div", { class: "price-tile" + (i === 0 && pr.tileTotal ? " is-primary" : "") }, [
              el("div", { class: "tile-label" }, [tile.label]),
              el("div", { class: "tile-num" }, [tile.num]),
              el("div", { class: "tile-unit" }, [tile.unit]),
            ]);
          })),
          pr.estimatedTotalNote ? el("p", { class: "price-total-note", html: pr.estimatedTotalNote }) : null,
        ]));
      }
      const cp = pr.chaperonePolicy;
      if (cp || pr.ratioNote || (pr.conditions || []).length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["CHAPERONES"]), el("h2", {}, [cp ? cp.headline : "Complimentary chaperones"])]),
          cp ? el("ul", { class: "assumptions-list" }, cp.lines.map(function (c) { return el("li", {}, [c]); }))
             : el("div", {}, [
                 pr.ratioNote ? el("p", { class: "price-ratio-note" }, [pr.ratioNote]) : null,
                 (pr.conditions || []).length ? el("ul", { class: "assumptions-list", style: "margin-top:10px;" }, pr.conditions.map(function (c) { return el("li", {}, [c]); })) : null,
               ]),
        ]));
      }
      if ((pr.assumptions || []).length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["PRICING BASED ON"])]),
          el("ul", { class: "assumptions-list" }, pr.assumptions.map(function (a) { return el("li", {}, [a]); })),
        ]));
      }
      if ((pr.whatCouldChange || []).length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["WHAT WOULD CHANGE YOUR TOTAL"])]),
          el("ul", { class: "assumptions-list" }, pr.whatCouldChange.map(function (a) { return el("li", {}, [a]); })),
          el("p", { class: "price-ratio-note", style: "margin-top:10px;" }, ["Any of these would come to you as a revised proposal before anything is final."]),
        ]));
      }
      s.appendChild(el("div", { class: "container" }, [bottomNav("What's Included", "sec-included", "Next Steps", "sec-next")]));
      return s;
    }

    function buildNext() {
      const s = el("section", { id: "sec-next", class: "page-section", "data-title": "Next Steps" });
      s.appendChild(heroBlock("next", PD.photos.next, PD.photoCredits.next));
      s.querySelector(".hero").appendChild(el("div", { class: "hero-inner container" }, [
        el("span", { class: "hero-eyebrow" }, ["NEXT STEPS"]),
        el("h1", {}, ["Ready to bring your students to REEF?"]),
        el("p", { class: "lede" }, ["Approve this proposal and REEF will prepare your contract, or tell us what you'd like to change."]),
      ]));
      s.appendChild(el("div", { class: "container block" }, [roadmap()]));
      if ((PD.confirmSummary || []).length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["WHAT YOU'RE APPROVING"]), el("h2", {}, ["Your program, in one place"])]),
          confirmSummaryList("on-light"),
        ]));
      }
      if ((PD.nextSteps || []).length) {
        s.appendChild(el("div", { class: "container block" }, [
          el("div", { class: "block-head" }, [el("div", { class: "rule" }), el("span", { class: "eyebrow" }, ["WHAT HAPPENS NEXT"])]),
          el("ol", { class: "next-steps-ol" }, PD.nextSteps.map(function (n) { return el("li", {}, [n]); })),
        ]));
      }
      const nextEmail = PD.cta.contactEmail || "explorers@REEF.org";
      s.appendChild(el("div", { class: "container block" }, [
        ctaModule(),
        el("p", { class: "cta-fine", style: "margin-top:14px;" }, [
          "Prefer email? Reach us directly at ",
          el("a", { href: "mailto:" + nextEmail, style: "color:inherit;text-decoration:underline;" }, [nextEmail]),
          ".",
        ]),
      ]));
      s.appendChild(el("div", { class: "container" }, [bottomNav("Pricing & Details", "sec-pricing", null, null)]));
      return s;
    }

    // ---------------- SHELL / ROUTER ----------------
    const SECTIONS = [
      { id: "sec-overview", label: "Overview", build: buildOverview },
      { id: "sec-experience", label: "Your Experience", build: buildExperience },
      { id: "sec-days", label: scheduleLabel, build: buildDays },
      { id: "sec-included", label: "What's Included", build: buildIncluded },
      { id: "sec-pricing", label: "Pricing & Details", build: buildPricing },
      { id: "sec-next", label: "Next Steps", build: buildNext },
    ];

    const pageRoot = document.querySelector(".page") || document.body;
    pageRoot.innerHTML = "";
    pageRoot.classList.add("proposal-shell");

    pageRoot.appendChild(el("a", { class: "skiplink", href: "#main" }, ["Skip to content"]));

    if (data.meta && data.meta.sampleFlag) {
      pageRoot.appendChild(el("div", { class: "sample-flag" }, [
        el("strong", {}, ["SAMPLE PROPOSAL — DESIGN REVIEW ONLY"]),
        "  ·  " + (data.meta.sampleFlagText || "illustrative content for layout review, not a confirmed itinerary or price"),
      ]));
    }

    pageRoot.appendChild(el("header", { id: "topbar" }, [
      el("div", { class: "topbar-row" }, [
        el("div", { class: "topbar-brand" }, [
          el("img", { class: "mark", src: defaultLogoPath(), alt: "" }),
          el("div", { class: "word" }, ["REEF", el("small", {}, ["Ocean Explorers"])]),
        ]),
        // QA walkthrough (2026-09-09): on narrow screens the chapter nav is
        // a horizontal scroller showing only a couple of items at a time,
        // so it wasn't obvious there were six sections at all. This counter
        // is hidden on wider screens (where the full nav is visible) and
        // shown only on mobile -- see .chapter-counter in styles.css.
        el("div", { class: "chapter-counter", id: "chapter-counter" }, ["1 / " + SECTIONS.length]),
        el("nav", { id: "chapter-nav", "aria-label": "Proposal sections" }),
      ]),
    ]));

    const main = el("main", { id: "main" });
    SECTIONS.forEach(function (s) { main.appendChild(s.build()); });
    pageRoot.appendChild(main);

    const nav = pageRoot.querySelector("#chapter-nav");
    SECTIONS.forEach(function (s, i) {
      nav.appendChild(el("button", { class: "chapter-link", "data-goto": s.id }, [
        el("span", { class: "chapter-num" }, [String(i + 1).padStart(2, "0")]), s.label,
      ]));
    });

    pageRoot.appendChild(el("footer", { id: "site-footer" }, [
      "Reef Environmental Education Foundation · P.O. Box 370246, Key Largo, FL 33037 · 305-852-0030 · ",
      el("a", { href: "https://www.reef.org" }, ["www.REEF.org"]),
      el("span", { class: "tag" }, ["Explore. Discover. Make a Difference."]),
    ]));

    function activateSection(id) {
      SECTIONS.forEach(function (s) {
        document.getElementById(s.id).classList.toggle("is-active", s.id === id);
      });
      pageRoot.querySelectorAll(".chapter-link").forEach(function (btn) {
        btn.setAttribute("aria-current", btn.getAttribute("data-goto") === id ? "true" : "false");
      });
      const counter = document.getElementById("chapter-counter");
      if (counter) {
        const idx = SECTIONS.findIndex(function (s) { return s.id === id; });
        counter.textContent = (idx === -1 ? 1 : idx + 1) + " / " + SECTIONS.length;
      }
    }

    // Real navigation (a chapter-nav click, or the URL's hash changing):
    // updates the section, syncs the URL, and scrolls to top. Note this
    // never runs on initial load -- see the plain activateSection() call
    // below instead, which deliberately skips history.replaceState().
    // (Calling history.replaceState() with a hash the very first time,
    // when the URL previously had none, makes at least this Chromium
    // build perform a native scroll-to-anchor before this script's own
    // "skip the scroll" logic can run -- which would otherwise tuck the
    // hero up under the sticky topbar on first paint. Deferring the
    // history write until a real navigation happens avoids that without
    // changing any of the original design's visible behavior.)
    function goTo(id, skipScroll) {
      const found = SECTIONS.some(function (s) { return s.id === id; });
      if (!found) id = SECTIONS[0].id;
      activateSection(id);
      if (location.hash.replace("#", "") !== id) history.replaceState(null, "", "#" + id);
      if (!skipScroll) window.scrollTo({ top: 0, behavior: "smooth" });
    }

    pageRoot.addEventListener("click", function (e) {
      const t = e.target.closest("[data-goto]");
      if (!t) return;
      e.preventDefault();
      goTo(t.getAttribute("data-goto"));
    });

    window.addEventListener("hashchange", function () {
      goTo(location.hash.replace("#", "") || SECTIONS[0].id, true);
    });

    activateSection(location.hash.replace("#", "") || SECTIONS[0].id);
  }

  // ---------------- CLOSING CTA + FOOTER ----------------
  function renderClosing(data) {
    const c = data.contacts || {};
    mount("closing-cta", el("div", { class: "closing-cta" }, [
      el("div", {}, [
        el("h3", {}, ["Ready for your students to become part of it?"]),
        el("p", {}, ["Reach out any time before your Expedition — a REEF educator is glad to help shape the details around your group."]),
      ]),
      el("div", { class: "contact" }, [
        el("div", { class: "eyebrow" }, ["REEF OCEAN EXPLORERS"]),
        el("div", {}, [
          el("a", { href: "mailto:" + (c.reefEmail || "info@REEF.org") }, [c.reefEmail || "info@REEF.org"]),
          " · " + (c.reefPhone || "305-852-0030"),
        ]),
      ]),
    ]));
    mount("site-footer", el("div", { class: "site-footer" }, [
      "Reef Environmental Education Foundation · P.O. Box 370246, Key Largo, FL 33037 · 305-852-0030 · ",
      el("a", { href: "https://www.reef.org" }, ["www.REEF.org"]),
      " · Explore. Discover. Make a Difference.",
    ]));
  }

  // ---------------- INIT ----------------
  function init() {
    const data = window.BOOKING_DATA;
    if (!data) {
      console.error("BOOKING_DATA is not defined. Make sure data.js loads before render.js.");
      return;
    }

    // docType "proposal" is a second, self-contained rendering mode (the
    // advanced six-section customer proposal experience) — it builds its
    // own shell and returns early rather than filling the mount points
    // below, which only the pre-trip/confirmed mode uses.
    if (data.docType === "proposal") {
      renderAdvancedProposal(data);
      return;
    }

    renderSampleFlag(data);
    renderHero(data);
    renderMiniNav(data);
    renderActionNeeded(data);
    if (data.docType === "pretrip") renderSnapshot(data);
    renderWelcome(data);
    renderGlance(data);
    renderDayByDay(data);
    renderWhatStudentsWillDo(data);
    renderGear(data);
    renderNextSteps(data);
    renderClosing(data);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
