"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { interpretCompletedCourses } from "../lib/courseInterpreter.js";

const commonCompletedCourseAliases: Record<string, string[]> = {
  // Keep this client-side fallback in sync with lib/courseInterpreter.js.
  "MATH 110A": ["calc 1", "calculus 1", "calculus one"],
  "MATH 110B": ["calc 2", "calculus 2", "calculus two"],
  "ECON 1": ["intro micro", "microeconomics", "econ 1"],
  "ECON 2": ["intro macro", "macroeconomics", "econ 2"],
  "STAT C1000": ["statistics", "stats", "intro stats"],
};

function normalize(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function equivalentCourseKeys(value: string) {
  const normalizedValue = normalize(value);
  const keys = new Set([normalizedValue]);

  for (const [courseCode, aliases] of Object.entries(
    commonCompletedCourseAliases
  )) {
    if (normalize(courseCode) === normalizedValue) {
      aliases.forEach((alias) => keys.add(normalize(alias)));
    }
  }

  return keys;
}

type Priority = "High" | "Medium" | "Low";

type CourseRequirement = {
  code: string;
  name: string;
  category: string;
  priority: Priority;
  prerequisites?: string[];
  prerequisiteOptions?: string[][];
  satisfiedBy?: string[][];
  aliases?: string[];
};

type GEFillerArea = {
  area: string;
  title: string;
  courses: CourseRequirement[];
};

type TransferPlan = {
  requiredCourses: CourseRequirement[];
  notes: string;
  competitivenessNote: string;
};

type RequirementDatabase = Record<
  string,
  Record<string, Record<string, TransferPlan>>
>;

type RequirementOptions = {
  colleges: string[];
  targetsByCollege: Record<string, string[]>;
  majorsByCollegeAndTarget: Record<string, Record<string, string[]>>;
};

type TransferResult = {
  completed: CourseRequirement[];
  missing: CourseRequirement[];
  recommended: CourseRequirement[];
  blocked: CourseRequirement[];
  sequence: CourseRequirement[][];
  readinessScore: number;
  competitiveness: string;
  notes: string;
  warning: string;
  error?: string;
};

const defaultRequirements: RequirementDatabase = {
  CCSF: {
    "UC Berkeley": {
      Economics: {
        notes:
          "Economics transfer is GPA-sensitive. This demo uses articulated CCSF courses from ASSIST-style agreements. Always verify final requirements on ASSIST.org.",
        competitivenessNote:
          "UC Berkeley Economics is competitive. GPA, major preparation, and course sequencing matter.",
        requiredCourses: [
          {
            code: "ECON 1",
            name: "Principles of Macroeconomics",
            category: "Required Lower Division",
            priority: "High",
            aliases: [
              "ECON1",
              "ECON 1",
              "MACRO",
              "MACROECONOMICS",
              "PRINCIPLES OF MACROECONOMICS",
            ],
          },
          {
            code: "ECON 3",
            name: "Principles of Microeconomics",
            category: "Required Lower Division",
            priority: "High",
            aliases: [
              "ECON3",
              "ECON 3",
              "MICRO",
              "MICROECONOMICS",
              "PRINCIPLES OF MICROECONOMICS",
            ],
          },
          {
            code: "MATH 110A",
            name: "Calculus I",
            category: "Required Lower Division",
            priority: "High",
            aliases: [
              "MATH110A",
              "MATH 110A",
              "MATH 110 A",
              "CALC 1",
              "CALCULUS I",
              "CALCULUS 1",
            ],
          },
          {
            code: "MATH 110B",
            name: "Calculus II",
            category: "Required Lower Division",
            priority: "High",
            prerequisites: ["MATH 110A"],
            aliases: [
              "MATH110B",
              "MATH 110B",
              "MATH 110 B",
              "CALC 2",
              "CALCULUS II",
              "CALCULUS 2",
            ],
          },
          {
            code: "STAT 20",
            name: "Introduction to Probability and Statistics",
            category: "Strongly Recommended",
            priority: "Medium",
            prerequisites: ["MATH 110A"],
            satisfiedBy: [["STAT 21"]],
            aliases: [
              "STAT20",
              "STAT 20",
              "STAT21",
              "STAT 21",
              "STATS",
              "STATISTICS",
              "PROBABILITY",
              "INTRO STATS",
              "BUSINESS STATS",
            ],
          },
        ],
      },

      "Data Science": {
        notes:
          "Data Science transfer is highly sequence-based. This demo uses the clearest articulated CCSF courses from ASSIST-style agreements. Always verify final requirements on ASSIST.org.",
        competitivenessNote:
          "UC Berkeley Data Science is competitive. Calculus, linear algebra, data science foundations, programming, and data structures preparation matter.",
        requiredCourses: [
          {
            code: "MATH 110A",
            name: "Calculus I",
            category: "Major Requirement",
            priority: "High",
            aliases: [
              "MATH110A",
              "MATH 110A",
              "MATH 110 A",
              "CALC 1",
              "CALCULUS I",
              "CALCULUS 1",
            ],
          },
          {
            code: "MATH 110B",
            name: "Calculus II",
            category: "Major Requirement",
            priority: "High",
            prerequisites: ["MATH 110A"],
            aliases: [
              "MATH110B",
              "MATH 110B",
              "MATH 110 B",
              "CALC 2",
              "CALCULUS II",
              "CALCULUS 2",
            ],
          },
          {
            code: "MATH 130",
            name: "Linear Algebra and Differential Equations",
            category: "Major Requirement",
            priority: "High",
            prerequisites: ["MATH 110B"],
            satisfiedBy: [["MATH 120", "MATH 125"]],
            aliases: [
              "MATH130",
              "MATH 130",
              "LINEAR ALGEBRA",
              "DIFFERENTIAL EQUATIONS",
              "LINEAR ALGEBRA AND DIFFERENTIAL EQUATIONS",
            ],
          },
          {
            code: "MATH 108",
            name: "Foundations of Data Science",
            category: "Highly Recommended",
            priority: "High",
            aliases: [
              "MATH108",
              "MATH 108",
              "DATA 8",
              "DATA C8",
              "FOUNDATIONS OF DATA SCIENCE",
            ],
          },
          {
            code: "ENGN 38",
            name: "Programming Concepts and Methodologies for Engineers",
            category: "Highly Recommended",
            priority: "Medium",
            aliases: [
              "ENGN38",
              "ENGN 38",
              "ENGINEERING 38",
              "PROGRAMMING CONCEPTS",
              "MATLAB",
              "ENGIN 7",
            ],
          },
          {
            code: "ENGN 10B",
            name: "Engineering Software Tools and Design",
            category: "Highly Recommended",
            priority: "Medium",
            aliases: [
              "ENGN10B",
              "ENGN 10B",
              "ENGINEERING 10B",
              "SOFTWARE TOOLS",
            ],
          },
          {
            code: "CS 110C",
            name: "Data Structures and Algorithms",
            category: "Highly Recommended",
            priority: "High",
            prerequisiteOptions: [["CS 110B"], ["CS 111B"]],
            satisfiedBy: [["CS 111C"]],
            aliases: [
              "CS110C",
              "CS 110C",
              "CS111C",
              "CS 111C",
              "DATA STRUCTURES",
              "DATA STRUCTURES C++",
              "DATA STRUCTURES JAVA",
              "COMPSCI 61B",
              "CS 61B",
            ],
          },
        ],
      },
    },

    UCLA: {
      Economics: {
        notes:
          "UCLA Economics lower-division major prep includes microeconomics, macroeconomics, calculus, and non-articulated UCLA courses that may need to be completed after transfer. Demo data only. Always verify on ASSIST.org.",
        competitivenessNote:
          "UCLA Economics is competitive. Complete articulated economics and calculus courses with strong grades before transfer.",
        requiredCourses: [
          {
            code: "ECON 3",
            name: "Principles of Microeconomics",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "ECON3",
              "ECON 3",
              "MICRO",
              "MICROECONOMICS",
              "PRINCIPLES OF MICROECONOMICS",
            ],
          },
          {
            code: "ECON 1",
            name: "Principles of Macroeconomics",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "ECON1",
              "ECON 1",
              "MACRO",
              "MACROECONOMICS",
              "PRINCIPLES OF MACROECONOMICS",
            ],
          },
          {
            code: "MATH 110A",
            name: "Calculus I",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "MATH110A",
              "MATH 110A",
              "MATH 110 A",
              "CALC 1",
              "CALCULUS I",
              "CALCULUS 1",
            ],
          },
          {
            code: "MATH 110B",
            name: "Calculus II",
            category: "Lower Division Major Requirement",
            priority: "High",
            prerequisites: ["MATH 110A"],
            aliases: [
              "MATH110B",
              "MATH 110B",
              "MATH 110 B",
              "CALC 2",
              "CALCULUS II",
              "CALCULUS 2",
            ],
          },
        ],
      },

      "Business Economics": {
        notes:
          "UCLA Business Economics lower-division major prep includes economics, accounting, and calculus. Demo data only. Always verify final requirements on ASSIST.org.",
        competitivenessNote:
          "UCLA Business Economics is highly competitive. Complete economics, accounting, and calculus courses with strong grades before transfer.",
        requiredCourses: [
          {
            code: "ECON 3",
            name: "Principles of Microeconomics",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "ECON3",
              "ECON 3",
              "MICRO",
              "MICROECONOMICS",
              "PRINCIPLES OF MICROECONOMICS",
            ],
          },
          {
            code: "ECON 1",
            name: "Principles of Macroeconomics",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "ECON1",
              "ECON 1",
              "MACRO",
              "MACROECONOMICS",
              "PRINCIPLES OF MACROECONOMICS",
            ],
          },
          {
            code: "ACCT 1",
            name: "Financial Accounting",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "ACCT1",
              "ACCT 1",
              "ACCOUNTING 1",
              "FINANCIAL ACCOUNTING",
              "MGMT 1A",
            ],
          },
          {
            code: "ACCT 2",
            name: "Managerial Accounting",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "ACCT2",
              "ACCT 2",
              "ACCOUNTING 2",
              "MANAGERIAL ACCOUNTING",
              "MGMT 1B",
            ],
          },
          {
            code: "MATH 110A",
            name: "Calculus I",
            category: "Lower Division Major Requirement",
            priority: "High",
            aliases: [
              "MATH110A",
              "MATH 110A",
              "MATH 110 A",
              "CALC 1",
              "CALCULUS I",
              "CALCULUS 1",
              "MATH 31A",
            ],
          },
          {
            code: "MATH 110B",
            name: "Calculus II",
            category: "Lower Division Major Requirement",
            priority: "High",
            prerequisites: ["MATH 110A"],
            aliases: [
              "MATH110B",
              "MATH 110B",
              "MATH 110 B",
              "CALC 2",
              "CALCULUS II",
              "CALCULUS 2",
              "MATH 31B",
            ],
          },
        ],
      },
    },
  },
};

const geFillerAreas: GEFillerArea[] = [
  {
    area: "Area 1A",
    title: "English Composition",
    courses: [
      {
        code: "ENGL C1000",
        name: "Academic Reading and Writing",
        category: "GE Filler — English Composition",
        priority: "Medium",
        aliases: ["ENGLC1000", "ENGLISH 1A", "ENGL 1A", "WRITING 1"],
      },
    ],
  },
  {
    area: "Area 1B",
    title: "Oral Communication / Critical Thinking",
    courses: [
      {
        code: "ENGL C1001",
        name: "Critical Thinking and Writing",
        category: "GE Filler — Critical Thinking",
        priority: "Low",
        aliases: ["ENGLC1001", "ENGLISH 1B", "ENGL 1B", "WRITING 2"],
      },
      {
        code: "COMM C1000",
        name: "Introduction to Public Speaking",
        category: "GE Filler — Communication",
        priority: "Low",
        aliases: ["COMMC1000", "COMM 1", "PUBLIC SPEAKING"],
      },
    ],
  },
  {
    area: "Area 2",
    title: "Math / Quantitative Reasoning",
    courses: [
      {
        code: "STAT C1000",
        name: "Introduction to Statistics",
        category: "GE Filler — Quantitative Reasoning",
        priority: "Medium",
        aliases: ["STATC1000", "STATISTICS", "STATS", "STAT"],
      },
    ],
  },
  {
    area: "Area 3",
    title: "Arts and Humanities",
    courses: [
      {
        code: "MUS 3A",
        name: "Music Appreciation",
        category: "GE Filler — Arts/Humanities",
        priority: "Low",
        aliases: ["MUS3A", "MUSIC APPRECIATION"],
      },
      {
        code: "CINE 18",
        name: "Introduction to Film Studies",
        category: "GE Filler — Arts/Humanities",
        priority: "Low",
        aliases: ["CINE18", "FILM", "FILM STUDIES"],
      },
      {
        code: "PHIL 2",
        name: "Introduction to Philosophy",
        category: "GE Filler — Arts/Humanities",
        priority: "Low",
        aliases: ["PHIL2", "PHILOSOPHY"],
      },
    ],
  },
  {
    area: "Area 4",
    title: "Social and Behavioral Sciences",
    courses: [
      {
        code: "PSYC C1000",
        name: "Introduction to Psychology",
        category: "GE Filler — Social Science",
        priority: "Low",
        aliases: ["PSYCC1000", "PSYCH", "PSYCHOLOGY"],
      },
      {
        code: "SOC 1",
        name: "Introduction to Sociology",
        category: "GE Filler — Social Science",
        priority: "Low",
        aliases: ["SOC1", "SOCIOLOGY"],
      },
    ],
  },
  {
    area: "Area 5",
    title: "Physical and Biological Sciences",
    courses: [
      {
        code: "ASTR 1",
        name: "Introduction to Astronomy",
        category: "GE Filler — Science",
        priority: "Low",
        aliases: ["ASTR1", "ASTRONOMY"],
      },
      {
        code: "OCAN 1",
        name: "Introduction to Oceanography",
        category: "GE Filler — Science",
        priority: "Low",
        aliases: ["OCAN1", "OCEANOGRAPHY"],
      },
      {
        code: "GEOL 10",
        name: "Physical Geology",
        category: "GE Filler — Science",
        priority: "Low",
        aliases: ["GEOL10", "GEOLOGY"],
      },
    ],
  },
  {
    area: "Area 6",
    title: "Ethnic Studies",
    courses: [
      {
        code: "ETHN 37",
        name: "Introduction to Ethnic Studies",
        category: "GE Filler — Ethnic Studies",
        priority: "Low",
        aliases: ["ETHN37", "IDST 37", "ETHNIC STUDIES"],
      },
      {
        code: "LALS 1",
        name: "Latina/o/x America",
        category: "GE Filler — Ethnic Studies",
        priority: "Low",
        aliases: ["LALS1", "LATINO STUDIES", "LATIN AMERICAN STUDIES"],
      },
    ],
  },
  {
    area: "Local Requirement",
    title: "U.S. History / Government",
    courses: [
      {
        code: "POLS C1000",
        name: "American Government and Politics",
        category: "GE Filler — U.S. History/Government",
        priority: "Low",
        aliases: ["POLSC1000", "AMERICAN GOVERNMENT", "GOVERNMENT"],
      },
      {
        code: "HIST 17A",
        name: "United States History",
        category: "GE Filler — U.S. History/Government",
        priority: "Low",
        aliases: ["HIST17A", "US HISTORY"],
      },
    ],
  },
  {
    area: "Local Requirement",
    title: "Health and Wellness",
    courses: [
      {
        code: "HLTH 10",
        name: "Health Education",
        category: "GE Filler — Health/Wellness",
        priority: "Low",
        aliases: ["HLTH10", "HEALTH"],
      },
      {
        code: "PE 28",
        name: "Physical Education",
        category: "GE Filler — Health/Wellness",
        priority: "Low",
        aliases: ["PE28", "PHYSICAL EDUCATION"],
      },
    ],
  },
];


function courseMatchesInput(course: CourseRequirement, rawInputs: string[]) {
  const acceptedNames = [
    course.code,
    course.name,
    ...(course.aliases ?? []),
  ].flatMap((name) => [...equivalentCourseKeys(name)]);

  return rawInputs.some((input) => acceptedNames.includes(normalize(input)));
}

function codeWasEntered(code: string, rawInputs: string[]) {
  const acceptedKeys = equivalentCourseKeys(code);

  return rawInputs.some((input) => acceptedKeys.has(normalize(input)));
}

function completedHasCode(
  code: string,
  completedCodes: Set<string>,
  rawInputs: string[]
) {
  return completedCodes.has(code) || codeWasEntered(code, rawInputs);
}

function requirementIsCompleted(course: CourseRequirement, rawInputs: string[]) {
  const directMatch = courseMatchesInput(course, rawInputs);

  const alternativeMatch =
    course.satisfiedBy?.some((courseSet) =>
      courseSet.every((code) => codeWasEntered(code, rawInputs))
    ) ?? false;

  return directMatch || alternativeMatch;
}

function uniqueCourses(courses: CourseRequirement[]) {
  const seen = new Set<string>();

  return courses.filter((course) => {
    if (seen.has(course.code)) return false;
    seen.add(course.code);
    return true;
  });
}

function priorityValue(priority: Priority) {
  if (priority === "High") return 1;
  if (priority === "Medium") return 2;
  return 3;
}

function prerequisitesMet(
  course: CourseRequirement,
  completedCodes: Set<string>,
  rawInputs: string[]
) {
  if (course.prerequisiteOptions && course.prerequisiteOptions.length > 0) {
    return course.prerequisiteOptions.some((option) =>
      option.every((prereq) =>
        completedHasCode(prereq, completedCodes, rawInputs)
      )
    );
  }

  return (course.prerequisites ?? []).every((prereq) =>
    completedHasCode(prereq, completedCodes, rawInputs)
  );
}

function buildSequence(
  missing: CourseRequirement[],
  completedCodes: Set<string>,
  rawInputs: string[]
) {
  const remaining = [...missing];
  const plannedCodes = new Set(completedCodes);
  const terms: CourseRequirement[][] = [];

  for (let term = 0; term < 4 && remaining.length > 0; term++) {
    const available = remaining
      .filter((course) => prerequisitesMet(course, plannedCodes, rawInputs))
      .sort((a, b) => priorityValue(a.priority) - priorityValue(b.priority))
      .slice(0, 3);

    if (available.length === 0) break;

    terms.push(available);

    for (const course of available) {
      plannedCodes.add(course.code);
    }

    for (const course of available) {
      const index = remaining.findIndex((item) => item.code === course.code);
      if (index !== -1) remaining.splice(index, 1);
    }
  }

  return terms;
}

function getCompetitiveness(score: number, note: string) {
  if (score >= 80) {
    return `Strong — most listed requirements are complete. ${note}`;
  }

  if (score >= 50) {
    return `Moderate — your plan is moving, but a few major prep courses still matter. ${note}`;
  }

  return `Needs improvement — complete more major prep before applying. ${note}`;
}

function formatRequirementOptions(options: string[][]) {
  return options.map((group) => group.join(" + ")).join(" OR ");
}

function getGEFillers(rawInputs: string[], amount: number) {
  const fillers: CourseRequirement[] = [];

  for (const area of geFillerAreas) {
    const areaAlreadyCompleted = area.courses.some((course) =>
      courseMatchesInput(course, rawInputs)
    );

    if (areaAlreadyCompleted) continue;

    const firstGoodOption = area.courses[0];

    if (firstGoodOption) {
      fillers.push(firstGoodOption);
    }

    if (fillers.length >= amount) break;
  }

  return fillers;
}

function buildRequirementOptions(database: RequirementDatabase) {
  const colleges = Object.keys(database).sort((a, b) => a.localeCompare(b));
  const targetsByCollege: Record<string, string[]> = {};
  const majorsByCollegeAndTarget: Record<string, Record<string, string[]>> = {};

  for (const college of colleges) {
    const targets = Object.keys(database[college] ?? {}).sort((a, b) =>
      a.localeCompare(b)
    );
    targetsByCollege[college] = targets;
    majorsByCollegeAndTarget[college] = {};

    for (const target of targets) {
      majorsByCollegeAndTarget[college][target] = Object.keys(
        database[college]?.[target] ?? {}
      ).sort((a, b) => a.localeCompare(b));
    }
  }

  return { colleges, targetsByCollege, majorsByCollegeAndTarget };
}

export default function PlannerClient() {
  const [assistOptions, setAssistOptions] = useState<RequirementOptions>({
    colleges: [],
    targetsByCollege: {},
    majorsByCollegeAndTarget: {},
  });
  const [assistRequirements, setAssistRequirements] = useState<RequirementDatabase>(
    defaultRequirements
  );

  const [communityCollege, setCommunityCollege] = useState("");
  const [targetSchool, setTargetSchool] = useState("");
  const [targetMajor, setTargetMajor] = useState("");
  const [completedCourses, setCompletedCourses] = useState("");
  const [result, setResult] = useState<TransferResult | null>(null);

  useEffect(() => {
    fetch('/data/assist_articulations.json')
      .then((res) => res.json())
      .then((data) => {
        const options = data.assistOptions ?? {
          colleges: [],
          targetsByCollege: {},
          majorsByCollegeAndTarget: {},
        };
        const requirements = data.assistRequirements ?? defaultRequirements;
        const defaultCollege = options.colleges[0] ?? "";
        const defaultTargetSchool =
          defaultCollege && options.targetsByCollege[defaultCollege]
            ? options.targetsByCollege[defaultCollege][0] ?? ""
            : "";
        const defaultTargetMajor =
          defaultCollege && defaultTargetSchool
            ? options.majorsByCollegeAndTarget[defaultCollege]?.[
                defaultTargetSchool
              ]?.[0] ?? ""
            : "";

        setAssistOptions(options);
        setAssistRequirements(requirements);
        setCommunityCollege(defaultCollege);
        setTargetSchool(defaultTargetSchool);
        setTargetMajor(defaultTargetMajor);
      })
      .catch((error) => {
        console.error('Failed to load articulation options:', error);
        const fallbackOptions = buildRequirementOptions(defaultRequirements);
        setAssistOptions(fallbackOptions);
        setAssistRequirements(defaultRequirements);
        setCommunityCollege('CCSF');
        setTargetSchool('UC Berkeley');
        setTargetMajor('Economics');
      });
  }, []);

  const requirements = assistRequirements;
  const options = assistOptions;
  const activeRequirements =
    Object.keys(requirements).length > 0 ? requirements : defaultRequirements;
  const fallbackOptions = useMemo(
    () => buildRequirementOptions(activeRequirements),
    [activeRequirements]
  );
  const activeOptions =
    options.colleges.length > 0 ? options : fallbackOptions;

  const collegeOptions = activeOptions.colleges;

  const selectedCollegeData = communityCollege
    ? activeRequirements[communityCollege] ?? {}
    : {};

  const schoolOptions = communityCollege
    ? activeOptions.targetsByCollege[communityCollege] ?? []
    : [];

  const selectedSchoolData = targetSchool
    ? selectedCollegeData[targetSchool] ?? {}
    : {};

  const majorOptions =
    communityCollege && targetSchool
      ? activeOptions.majorsByCollegeAndTarget[communityCollege]?.[
          targetSchool
        ] ?? []
      : [];

  const selectedPlan = targetMajor ? selectedSchoolData[targetMajor] : null;

  const previewPlan =
    activeRequirements.CCSF?.["UC Berkeley"]?.["Economics, B.A."] ??
    activeRequirements.CCSF?.["UC Berkeley"]?.Economics ??
    defaultRequirements.CCSF["UC Berkeley"].Economics;

  const previewCompleted = previewPlan.requiredCourses.filter((course) =>
    ["ECON 1", "MATH 110A"].includes(course.code)
  );

  const previewMissing = previewPlan.requiredCourses.filter((course) =>
    ["ECON 3", "MATH 110B", "STAT 20"].includes(course.code)
  );

  const previewRecommended = previewPlan.requiredCourses.filter((course) =>
    ["MATH 110B", "ECON 3", "STAT 20"].includes(course.code)
  );

  const readinessLabel = useMemo(() => {
    if (!result) return "Preview";
    if (result.readinessScore >= 80) return "Strong";
    if (result.readinessScore >= 50) return "Moderate";
    return "Needs Work";
  }, [result]);

  function resetResults() {
    setResult(null);
  }

  function checkTransferPlan() {
    if (!selectedPlan) {
      setResult({
        completed: [],
        missing: [],
        recommended: [],
        blocked: [],
        sequence: [],
        readinessScore: 0,
        competitiveness: "",
        notes:
          "Choose a current college, target university, and target major before generating a plan.",
        warning: "",
        error: "Plan not found.",
      });
      return;
    }

    const { matchedCourses: rawCompleted, uncertainMatches } = interpretCompletedCourses(
      completedCourses,
      activeRequirements
    );

    const completed = selectedPlan.requiredCourses.filter((course) =>
      requirementIsCompleted(course, rawCompleted)
    );

    const completedCodes = new Set(completed.map((course) => course.code));

    const missing = selectedPlan.requiredCourses.filter(
      (course) => !completedCodes.has(course.code)
    );

    const availableNow = missing.filter((course) =>
      prerequisitesMet(course, completedCodes, rawCompleted)
    );

    const blocked = missing.filter(
      (course) => !prerequisitesMet(course, completedCodes, rawCompleted)
    );

    const majorRecommended = uniqueCourses(
      availableNow.sort(
        (a, b) => priorityValue(a.priority) - priorityValue(b.priority)
      )
    ).slice(0, 3);

    const geFillers = getGEFillers(
      rawCompleted,
      Math.max(0, 4 - majorRecommended.length)
    );

    const recommended = uniqueCourses([...majorRecommended, ...geFillers]).slice(
      0,
      4
    );

    const readinessScore = Math.round(
      (completed.length / selectedPlan.requiredCourses.length) * 100
    );

    const sequence = buildSequence(missing, completedCodes, rawCompleted);

    const uncertaintyWarning = uncertainMatches.length
      ? `Some completed courses were ambiguous or could not be resolved exactly: ${uncertainMatches
          .map((item) => item.input)
          .join(', ')}. Verify your entries and the final plan with a counselor.`
      : "";

    setResult({
      completed,
      missing,
      recommended,
      blocked,
      sequence,
      readinessScore,
      competitiveness: getCompetitiveness(
        readinessScore,
        selectedPlan.competitivenessNote
      ),
      notes: selectedPlan.notes,
      warning: [
        "GE filler classes are not major requirements. Use them only to balance your schedule, and verify all GE/transfer requirements with ASSIST.org and a counselor.",
        uncertaintyWarning,
      ]
        .filter(Boolean)
        .join(' '),
    });
  }

  return (
    <main className="min-h-screen bg-[#eee9df] text-[#2f3135]">
      <section className="mx-auto max-w-7xl px-5 py-6 md:px-8">
        <nav className="mb-12 flex items-center justify-between border-b border-[#d8d0c3] pb-5">
          <div className="flex items-center gap-6">
            <img
              src="/coursebridge-logo.png"
              alt="CourseBridge logo"
              className="h-60 w-auto mix-blend-multiply"
            />

            <p className="text-xl leading-tight text-[#7b818b]">
              Transfer planning for community college students
            </p>
          </div>

          <a
            href="#planner"
            className="hidden rounded-xl bg-[#0b7f46] px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[#08683a] md:block"
          >
            Build your plan
          </a>
        </nav>

        <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr]">
          <section className="pt-4">
            <p className="mb-4 inline-flex rounded-full border border-[#b8d8c7] bg-[#e7f3ed] px-4 py-2 text-sm font-semibold text-[#0b7f46]">
              Built around real transfer planning problems
            </p>

            <h1 className="max-w-3xl text-5xl font-bold leading-tight tracking-tight text-[#303236] md:text-6xl">
              Know exactly what classes you need before you transfer.
            </h1>

            <p className="mt-5 max-w-2xl text-lg leading-8 text-[#6f7680]">
              CourseBridge helps community college students plan UC and CSU
              transfer requirements using their completed courses, target
              school, and major.
            </p>

            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <a
                href="#planner"
                className="rounded-xl bg-[#0b7f46] px-5 py-3 text-center font-semibold text-white shadow-sm transition hover:bg-[#08683a]"
              >
                Build My Transfer Plan
              </a>

              <a
                href="#example"
                className="rounded-xl border border-[#d1c7b8] bg-[#faf8f3] px-5 py-3 text-center font-semibold text-[#303236] transition hover:bg-white"
              >
                See Example Plan
              </a>
            </div>

            <div className="mt-10 grid gap-3 sm:grid-cols-2">
              <PainPoint text="ASSIST.org can be hard to read." />
              <PainPoint text="Requirements change by school and major." />
              <PainPoint text="One missing prerequisite can delay transfer." />
              <PainPoint text="Counselors help, but appointments fill up fast." />
            </div>
          </section>

          <section className="rounded-3xl border border-[#d8d0c3] bg-[#faf8f3] p-6 shadow-[0_18px_45px_rgba(67,54,36,0.08)]">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-[#7b818b]">
                  Product preview
                </p>
                <h2 className="mt-1 text-2xl font-bold text-[#303236]">
                  UC Berkeley · Economics
                </h2>
              </div>

              <span className="rounded-full border border-[#f0c15d] bg-[#fff7db] px-3 py-1 text-sm font-semibold text-[#8a6100]">
                Moderate
              </span>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2">
              <PreviewCard
                title="Completed"
                items={previewCompleted.map((course) => course.name)}
              />

              <PreviewCard
                title="Missing"
                items={previewMissing.map((course) => course.name)}
              />
            </div>

            <div className="mt-4 rounded-2xl border border-[#d8d0c3] bg-white p-4">
              <p className="mb-3 text-sm font-semibold text-[#303236]">
                Recommended next term
              </p>

              <div className="flex flex-wrap gap-2">
                {previewRecommended.map((course) => (
                  <span
                    key={course.code}
                    className="rounded-lg bg-[#e7f3ed] px-3 py-2 text-sm font-semibold text-[#0b7f46]"
                  >
                    {course.name}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-4 rounded-2xl border border-[#ef9a9a] bg-[#fff0f0] p-4">
              <p className="font-semibold text-[#9b1c1c]">Warning</p>
              <p className="mt-2 text-sm leading-6 text-[#7f1d1d]">
                GE filler classes can help balance your schedule, but they are
                not a substitute for major prep. Always verify with ASSIST.org
                and a counselor.
              </p>
            </div>
          </section>
        </div>

        <section className="mt-14 grid gap-5 md:grid-cols-3">
          <Step number="1" title="Add your courses">
            Enter your completed courses in plain text.
          </Step>

          <Step number="2" title="Pick a UC/CSU and major">
            Choose the campus and major you want to transfer into.
          </Step>

          <Step number="3" title="Get a clear plan">
            See major requirements, blocked classes, and lighter GE filler
            options.
          </Step>
        </section>

        <section
          id="planner"
          className="mt-16 grid gap-6 lg:grid-cols-[0.72fr_1.28fr]"
        >
          <div className="rounded-3xl border border-[#d8d0c3] bg-[#faf8f3] p-6 shadow-[0_18px_45px_rgba(67,54,36,0.08)]">
            <h2 className="text-3xl font-bold text-[#303236]">
              Build your plan
            </h2>

            <p className="mt-3 text-base leading-7 text-[#7b818b]">
              Major prep comes first. If your schedule has room, CourseBridge
              adds lighter GE filler classes.
            </p>

            <form className="mt-8 space-y-5">
              <SelectField
                label="Current college"
                value={communityCollege}
                options={collegeOptions}
                onChange={(value) => {
                  const nextSchool =
                    activeOptions.targetsByCollege[value]?.[0] ?? "";
                  const nextMajor =
                    activeOptions.majorsByCollegeAndTarget[value]?.[nextSchool]?.[0] ??
                    "";

                  setCommunityCollege(value);
                  setTargetSchool(nextSchool);
                  setTargetMajor(nextMajor);
                  resetResults();
                }}
              />

              <SelectField
                label="Target university"
                value={targetSchool}
                options={schoolOptions}
                onChange={(value) => {
                  const nextMajor =
                    activeOptions.majorsByCollegeAndTarget[communityCollege]?.[
                      value
                    ]?.[0] ?? "";

                  setTargetSchool(value);
                  setTargetMajor(nextMajor);
                  resetResults();
                }}
              />

              <SelectField
                label="Target major"
                value={targetMajor}
                options={majorOptions}
                onChange={(value) => {
                  setTargetMajor(value);
                  resetResults();
                }}
              />

              <label className="block">
                <span className="mb-2 block text-sm font-bold text-[#303236]">
                  Completed courses
                </span>

                <textarea
                  value={completedCourses}
                  onChange={(event) => {
                    const v = event.target.value;
                    setCompletedCourses(v);
                    resetResults();
                  }}
                  className="min-h-40 w-full rounded-2xl border border-[#d1c7b8] bg-white px-4 py-3 text-sm text-[#303236] outline-none transition placeholder:text-[#a2a7af] focus:border-[#0b7f46] focus:ring-4 focus:ring-[#0b7f46]/10"
                  placeholder="Example: econ1, math110a, math130, cs111c"
                />

              </label>

              <button
                type="button"
                onClick={checkTransferPlan}
                className="w-full rounded-2xl bg-[#0b7f46] px-5 py-4 text-lg font-bold text-white shadow-sm transition hover:bg-[#08683a]"
              >
                Generate Plan
              </button>
            </form>
          </div>

          <div className="rounded-3xl border border-[#d8d0c3] bg-[#faf8f3] p-6 shadow-[0_18px_45px_rgba(67,54,36,0.08)]">
            {!result && <EmptyDashboard />}

            {result?.error && (
              <div className="rounded-2xl border border-[#ef9a9a] bg-[#fff0f0] p-6">
                <h3 className="text-xl font-bold text-[#9b1c1c]">
                  {result.error}
                </h3>

                <p className="mt-2 text-[#7f1d1d]">{result.notes}</p>
              </div>
            )}

            {result && !result.error && (
              <div>
                <div className="flex flex-col gap-4 border-b border-[#d8d0c3] pb-5 md:flex-row md:items-start md:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-[#7b818b]">
                      Personalized plan
                    </p>

                    <h2 className="mt-1 text-3xl font-bold text-[#303236]">
                      {targetSchool} · {targetMajor}
                    </h2>
                  </div>

                  <div className="rounded-2xl border border-[#b8d8c7] bg-[#e7f3ed] px-5 py-4 text-center">
                    <p className="text-sm font-bold text-[#0b7f46]">
                      Readiness
                    </p>

                    <p className="text-3xl font-bold text-[#0b7f46]">
                      {result.readinessScore}%
                    </p>
                  </div>
                </div>

                <div className="mt-5 rounded-2xl border border-[#d8d0c3] bg-white p-4">
                  <p className="font-bold text-[#303236]">
                    Competitiveness estimate
                  </p>
                  <p className="mt-2 text-sm leading-6 text-[#6f7680]">
                    {result.competitiveness}
                  </p>
                </div>

                <div className="mt-6 h-3 overflow-hidden rounded-full bg-[#e0d9cf]">
                  <div
                    className="h-full rounded-full bg-[#0b7f46]"
                    style={{ width: `${result.readinessScore}%` }}
                  />
                </div>

                <div className="mt-2 flex items-center justify-between text-sm text-[#7b818b]">
                  <span>Status: {readinessLabel}</span>
                  <span>{result.completed.length} completed</span>
                </div>

                <div className="mt-6 grid gap-5 md:grid-cols-2">
                  <CoursePanel
                    title="Completed requirements"
                    tone="complete"
                    courses={result.completed}
                    empty="No matched requirements yet."
                  />

                  <CoursePanel
                    title="Missing requirements"
                    tone="missing"
                    courses={result.missing}
                    empty="No missing requirements."
                  />

                  <CoursePanel
                    title="Recommended next courses"
                    tone="recommended"
                    courses={result.recommended}
                    empty="No recommended courses."
                  />

                  <CoursePanel
                    title="Blocked by course order"
                    tone="blocked"
                    courses={result.blocked}
                    empty="No blocked courses."
                  />
                </div>

                <div className="mt-6 rounded-2xl border border-[#d8d0c3] bg-white p-5">
                  <h3 className="font-bold text-[#303236]">
                    Possible course sequence
                  </h3>

                  {result.sequence.length === 0 ? (
                    <p className="mt-2 text-sm text-[#7b818b]">
                      No sequence needed yet.
                    </p>
                  ) : (
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      {result.sequence.map((term, index) => (
                        <div
                          key={`term-${index}`}
                          className="rounded-2xl border border-[#d8d0c3] bg-[#faf8f3] p-4"
                        >
                          <p className="mb-3 font-bold text-[#303236]">
                            Term {index + 1}
                          </p>

                          <div className="space-y-2">
                            {term.map((course) => (
                              <p
                                key={course.code}
                                className="text-sm text-[#6f7680]"
                              >
                                {course.code} — {course.name}
                              </p>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="mt-5 rounded-2xl border border-[#ef9a9a] bg-[#fff0f0] p-4">
                  <p className="font-bold text-[#9b1c1c]">Warning</p>

                  <p className="mt-2 text-sm leading-6 text-[#7f1d1d]">
                    {result.warning}
                  </p>
                </div>

                <div className="mt-5 rounded-2xl border border-[#d8d0c3] bg-white p-4">
                  <p className="font-bold text-[#303236]">
                    Counselor-ready notes
                  </p>

                  <p className="mt-2 text-sm leading-6 text-[#6f7680]">
                    {result.notes}
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>

        <footer className="mt-10 border-t border-[#d8d0c3] pt-5 text-sm text-[#7b818b]">
          Demo data only. CourseBridge is independent and not affiliated with
          ASSIST, UC, CSU, or CCSF. Always verify requirements through
          ASSIST.org, official college catalogs, and a counselor.
        </footer>
      </section>
    </main>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-bold text-[#303236]">
        {label}
      </span>

      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border border-[#d1c7b8] bg-white px-4 py-3 text-sm text-[#303236] outline-none transition focus:border-[#0b7f46] focus:ring-4 focus:ring-[#0b7f46]/10"
      >
        <option value="" disabled>
          Select {label.toLowerCase()}
        </option>

        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function PainPoint({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-[#d8d0c3] bg-[#faf8f3] p-4 text-sm font-medium text-[#4d535c] shadow-sm">
      {text}
    </div>
  );
}

function Step({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-[#d8d0c3] bg-[#faf8f3] p-5 shadow-[0_18px_45px_rgba(67,54,36,0.06)]">
      <div className="mb-4 flex h-9 w-9 items-center justify-center rounded-full bg-[#0b7f46] text-sm font-bold text-white">
        {number}
      </div>

      <h3 className="text-xl font-bold text-[#303236]">{title}</h3>

      <p className="mt-2 leading-6 text-[#6f7680]">{children}</p>
    </div>
  );
}

function PreviewCard({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-2xl border border-[#d8d0c3] bg-white p-4">
      <p className="mb-3 text-sm font-bold text-[#303236]">{title}</p>

      <div className="space-y-2">
        {items.map((item) => (
          <p key={item} className="text-sm text-[#6f7680]">
            {item}
          </p>
        ))}
      </div>
    </div>
  );
}

function EmptyDashboard() {
  return (
    <div className="flex min-h-[560px] items-center justify-center rounded-3xl border border-dashed border-[#d8d0c3] bg-white/60 p-8 text-center">
      <div>
        <p className="text-3xl font-bold text-[#303236]">
          Your transfer plan will appear here.
        </p>

        <p className="mt-4 max-w-md text-lg leading-8 text-[#7b818b]">
          Choose a current college, target university, and major. Then enter
          your completed courses and generate a plan.
        </p>
      </div>
    </div>
  );
}

function CoursePanel({
  title,
  courses,
  tone,
  empty,
}: {
  title: string;
  courses: CourseRequirement[];
  tone: "complete" | "missing" | "recommended" | "blocked";
  empty: string;
}) {
  const styles = {
    complete: "border-[#b8d8c7] bg-[#e7f3ed]",
    missing: "border-[#f0c15d] bg-[#fff7db]",
    recommended: "border-[#b7cce5] bg-[#eef5ff]",
    blocked: "border-[#ef9a9a] bg-[#fff0f0]",
  };

  return (
    <div className={`rounded-2xl border p-5 ${styles[tone]}`}>
      <h3 className="font-bold text-[#303236]">{title}</h3>

      {courses.length === 0 ? (
        <p className="mt-3 text-sm text-[#7b818b]">{empty}</p>
      ) : (
        <div className="mt-4 space-y-3">
          {courses.map((course) => (
            <CourseItem key={course.code} course={course} />
          ))}
        </div>
      )}
    </div>
  );
}

function CourseItem({ course }: { course: CourseRequirement }) {
  return (
    <div className="rounded-xl border border-[#d8d0c3] bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-bold text-[#303236]">
            {course.code} — {course.name}
          </p>

          <p className="mt-1 text-xs text-[#7b818b]">{course.category}</p>

          {course.prerequisites && course.prerequisites.length > 0 && (
            <p className="mt-2 text-xs font-bold text-[#8a6100]">
              Prereq: {course.prerequisites.join(", ")}
            </p>
          )}

          {course.prerequisiteOptions &&
            course.prerequisiteOptions.length > 0 && (
              <p className="mt-2 text-xs font-bold text-[#8a6100]">
                Prereq: {formatRequirementOptions(course.prerequisiteOptions)}
              </p>
            )}

          {course.satisfiedBy && course.satisfiedBy.length > 0 && (
            <p className="mt-2 text-xs font-bold text-[#0b7f46]">
              Also satisfied by: {formatRequirementOptions(course.satisfiedBy)}
            </p>
          )}
        </div>

        <span className="rounded-full border border-[#d8d0c3] bg-[#faf8f3] px-2 py-1 text-xs font-bold text-[#4d535c]">
          {course.priority}
        </span>
      </div>
    </div>
  );
}
