/* ============================================================
   Sample booking data — Confirmed/Pre-Trip Packet
   ------------------------------------------------------------
   This is a WORKED EXAMPLE matching the sample packet Martha
   supplied (REEF_OceanExplorers_Sample_PreTrip_Packet), rebuilt
   as data rather than hand-written HTML — proving the render.js
   shell reproduces that design from a plain data object.

   Every field here is exactly the kind of field the REEF
   Bookings Airtable record + Activities table already carries
   (see OXP_EPO_Corrected_Architecture_v1.md and the Activities
   table schema) - once the generator exists, this file is what
   it should produce automatically per booking. For now it is
   hand-filled to prove the page.

   [Bracketed] values are the ones the format spec explicitly
   flags as "confirm from booking data" placeholders.
   ============================================================ */

window.BOOKING_DATA = {
  docType: "pretrip",
  assetDepth: 2, // this file lives at bookings/<slug>/data.js, two levels below assets/

  meta: {
    sampleFlag: true,
  },

  program: {
    name: "Florida Keys Marine Science Expedition",
    track: "Expedition",
    groupName: "[Group / School Name]",
    schoolOrg: "[Group / School Name]",
    gradeLevel: "[Grade / Audience]",
    groupSize: "[# Students / Chaperones]",
    location: "REEF Campus, Key Largo",
    dates: { label: "Draft", range: "[Draft Date Range, 2026]" },
  },

  contacts: {
    educatorName: "[Educator / Group Leader]",
    reefEducatorName: "[REEF Educator Name]",
    reefPhone: "305-852-0030",
    reefEmail: "info@REEF.org",
  },

  hero: {
    kicker: "OCEAN EXPLORERS\nEXPEDITION PACKET",
    eyebrowTag: "Florida Keys Marine Science Expedition",
    headline: "From Student to Scientist in Key Largo",
    promise: "Turn the ocean into your classroom. Your students won't just study marine science — they become part of it.",
  },

  welcome: {
    body: [
      "We're glad your group is joining us. This packet lays out what to expect from your Florida Keys Marine Science Expedition — where your students will identify reef fish, explore real coral reef, mangrove, and seagrass habitats, and practice the same citizen-science methods REEF's volunteer network uses across the Caribbean and beyond.",
      "This is not a sightseeing trip. It's a working expedition: your students will observe, identify, survey, investigate, and contribute — and leave with a real sense of what it means to practice marine science, not just read about it.",
    ],
    signOff: "The REEF Ocean Explorers Team",
  },

  glanceNote: "A quick-scan summary for planning. Full detail — including “students will” outcomes and gear notes — follows on the day-by-day pages.",

  days: [
    {
      dayNumber: 1,
      totalDays: 2,
      title: "From Student to Scientist",
      theme: "Students move from the classroom to the reef — learning fish ID, then applying it in the field.",
      morningLabel: "Campus check-in & orientation; Florida Keys fish & adaptations",
      afternoonLabel: "Offshore coral reef snorkel & fish survey",
      learningOutcome: "Fish ID in context; reef ecology in the field",
      blocks: [
        {
          time: "8:30 AM",
          tag: "Campus",
          title: "REEF Campus check-in & expedition orientation",
          description: "Students arrive at the REEF Campus, meet their REEF educators, and get oriented to the days ahead — framing the trip as an immersive Florida Keys marine science experience, not a sightseeing tour.",
        },
        {
          time: "9:15 AM",
          tag: "Campus Session",
          title: "Florida Keys fish & adaptations",
          description: "A REEF educator leads a hands-on session on how body shape, color, and behavior help reef fish survive — building the fish-identification skills students will apply on the reef.",
        },
        {
          time: "11:00 AM",
          tag: "Lunch & Change",
          title: "Lunch, hydration & gear-up",
          description: "Time to eat, hydrate, apply reef-safe sun protection, and change for the water before departing for the boat.",
        },
        {
          time: "12:30 PM",
          tag: "REEF · Boat",
          title: "Offshore coral reef snorkel & fish survey",
          description: "Students travel by boat to a Florida Keys coral reef to practice fish identification, observe reef ecology firsthand, and connect their field observations to REEF's citizen-science survey program.",
        },
        {
          time: "4:00 PM",
          tag: "Wrap-Up",
          title: "Return to campus & reflection",
          description: "Group returns to the REEF Campus to rinse gear, log survey observations, and reflect on the day's dive into reef ecology.",
        },
      ],
      studentsWill: [
        "Practice fish identification in context, on the reef.",
        "Observe how reef habitat structure supports marine life.",
        "Connect field observations to REEF's citizen-science survey methods.",
      ],
      bring: "mask, snorkel, fins, towel, reusable water bottle, reef-safe sun protection",
      note: "boat and water activities are weather- and water-condition dependent",
    },
    {
      dayNumber: 2,
      totalDays: 2,
      title: "Coastal Ecosystems & Conservation",
      theme: "Students trade the reef for the coastline, then investigate one of its biggest conservation challenges.",
      morningLabel: "State park mangrove & seagrass kayak ecology tour",
      afternoonLabel: "Lionfish invasion lesson & guided dissection",
      learningOutcome: "Coastal habitat function; invasive species & conservation",
      blocks: [
        {
          time: "9:00 AM",
          tag: "Kayak · State Park",
          title: "Mangrove & seagrass kayak ecology tour",
          description: "Students paddle a Florida state park's mangrove and seagrass habitat, investigating how these coastal ecosystems shelter marine life, protect shorelines, and connect to the health of the reef beyond.",
        },
        {
          time: "12:00 PM",
          tag: "Lunch & Change",
          title: "Lunch, hydration & change",
          description: "Time to eat, dry off, and change before the afternoon campus session.",
        },
        {
          time: "1:15 PM",
          tag: "Campus · Lab",
          title: "Invasive lionfish lesson & guided dissection",
          description: "Students investigate invasive lionfish through a hands-on lesson and guided dissection, linking anatomy and adaptation to a real conservation challenge facing Florida Keys reef ecosystems.",
        },
        {
          time: "3:00 PM",
          tag: "Closing",
          title: "Reflection & departure",
          description: "The expedition closes by connecting the experience back to student learning: what they observed, what questions they can keep asking, and how citizen science turns curiosity into conservation action.",
        },
      ],
      studentsWill: [
        "Explain how mangrove and seagrass habitats support reef health.",
        "Investigate an invasive species through hands-on dissection.",
        "Connect classroom conservation concepts to real field evidence.",
      ],
      bring: "closed-toe water shoes, hat, sun protection, reusable water bottle",
      note: "kayak route may adjust for weather and water conditions",
    },
  ],

  gear: {
    groups: [
      {
        title: "Water Gear",
        items: [
          { label: "Mask, snorkel, fins [from booking data]", level: "required" },
          { label: "Rash guard or swimsuit under clothing", level: "recommended" },
          { label: "Reef-safe sunscreen", level: "recommended" },
        ],
      },
      {
        title: "Clothing & Everyday Gear",
        items: [
          { label: "Closed-toe water shoes for the kayak day" },
          { label: "Hat and sun protection" },
          { label: "Reusable water bottle" },
          { label: "Change of clothes and towel" },
        ],
      },
      {
        title: "Forms & Readiness",
        items: [
          { label: "Signed waiver on file for each participant [confirm form name from booking data]", level: "required" },
          { label: "Medical/health form on file, including any allergies or accommodations", level: "required" },
          { label: "Any dive or snorkel certification requirements will be confirmed based on the activities included in your program" },
          { label: "Teacher/chaperone notes on group readiness, swimming comfort, or accommodations are welcome in advance" },
        ],
      },
    ],
  },

  flexNote: "Final activities and timing may adjust for weather, water conditions, vendor availability, and group readiness. Your REEF educator will communicate any day-of changes to your group leader directly.",

  finalReminders: {
    arrivalTime: "",
    parking: "",
    reefContact: "",
    questionsEmail: "info@REEF.org",
  },
};
