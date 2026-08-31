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
     hero: { eyebrowTag, headline, promise },
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

    mount("hero", el("div", { class: "hero" }, [
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
          el("h2", {}, [days.length + " day" + (days.length > 1 ? "s" : "") + ", one Florida Keys expedition"]),
          el("p", { class: "dek" }, [data.glanceNote ||
            "A quick-scan summary for planning. Full detail — including “students will” outcomes and gear notes — follows on the day-by-day pages."]),
        ]),
        el("table", { class: "glance-table" }, [
          el("thead", {}, [el("tr", {}, ["Day", "Theme", "Morning", "Afternoon", "Learning Outcome"].map(function (h) {
            return el("th", {}, [h]);
          }))]),
          el("tbody", {}, rows),
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

  // ---------------- FLEX / FINAL REMINDERS ----------------
  function renderFinalReminders(data) {
    const fr = data.finalReminders || {};
    mount("final-reminders", el("div", { class: "section" }, [
      el("div", { class: "container" }, [
        el("div", { class: "section-head" }, [
          el("div", { class: "divider-mark" }),
          el("span", { class: "eyebrow" }, ["FINAL REMINDERS"]),
          el("h2", {}, ["Before you arrive"]),
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

  // ---------------- PROPOSAL-ONLY: WHY THIS WORKS + NEXT STEPS ----------------
  function renderProposalExtras(data) {
    const prop = data.proposal || {};
    if (prop.whyItWorks && prop.whyItWorks.length) {
      mount("why-it-works", el("div", { class: "section" }, [
        el("div", { class: "container" }, [
          el("div", { class: "section-head" }, [
            el("div", { class: "divider-mark" }),
            el("span", { class: "eyebrow" }, ["WHY THIS EXPEDITION WORKS"]),
            el("h2", {}, ["Real ecosystems. Real participation. Real conservation."]),
          ]),
          el("div", { class: "will-grid" }, prop.whyItWorks.map(function (item) {
            return el("div", { class: "will-card" }, [
              el("span", { class: "verb" }, [item.title]),
              el("p", {}, [item.text]),
            ]);
          })),
        ]),
      ]));
    }
    if (prop.nextSteps && prop.nextSteps.length) {
      mount("next-steps", el("div", { class: "section" }, [
        el("div", { class: "container" }, [
          el("div", { class: "section-head" }, [
            el("div", { class: "divider-mark" }),
            el("span", { class: "eyebrow" }, ["NEXT STEPS"]),
            el("h2", {}, ["Start planning your student experience"]),
          ]),
          el("div", { class: "gear-card" }, [
            el("ul", {}, prop.nextSteps.map(function (step) {
              return el("li", { style: "margin-bottom:8px;" }, ["→ " + step]);
            })),
          ]),
        ]),
      ]));
    }
  }

  // ---------------- CLOSING CTA + FOOTER ----------------
  function renderClosing(data) {
    const c = data.contacts || {};
    mount("closing-cta", el("div", { class: "closing-cta" }, [
      el("div", {}, [
        el("h3", {}, ["Ready for your students to become part of it?"]),
        el("p", {}, ["Reach out any time before your expedition — a REEF educator is glad to help shape the details around your group."]),
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
    renderSampleFlag(data);
    renderHero(data);
    if (data.docType === "pretrip") renderSnapshot(data);
    renderWelcome(data);
    renderGlance(data);
    renderDayByDay(data);
    if (data.docType === "proposal") {
      renderProposalExtras(data);
    } else {
      renderWhatStudentsWillDo(data);
      renderGear(data);
      renderFinalReminders(data);
    }
    renderClosing(data);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
