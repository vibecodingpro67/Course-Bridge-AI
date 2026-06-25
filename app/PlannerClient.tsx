"use client";

import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
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

// Extract subject code from course code (e.g., "MATH 110A" -> "MATH")
function getSubject(courseCode: string): string {
  const match = courseCode.match(/^([A-Z]+)/);
  return match ? match[1] : "OTHER";
}

// Determine difficulty level for a course
function getCourseDifficulty(course: CourseRequirement): 'hard' | 'medium' | 'light' {
  const subject = getSubject(course.code);
  const code = course.code.toUpperCase();

  // Hard STEM courses
  const hardSubjects = ['MATH', 'PHYSICS', 'CHEM', 'CS', 'ENGR'];
  const hardKeywords = ['CALCULUS', 'LINEAR ALGEBRA', 'PHYSICS', 'LAB', 'DATA STRUCTURES'];
  
  if (hardSubjects.includes(subject)) return 'hard';
  if (hardKeywords.some(kw => code.includes(kw) || course.name.includes(kw))) return 'hard';
  
  // Medium courses
  const mediumSubjects = ['ECON', 'STAT', 'ASTRON', 'BIOL', 'CHEM'];
  if (mediumSubjects.includes(subject)) return 'medium';
  
  // Light courses (writing, GE, intro surveys)
  return 'light';
}

// Count hard courses in a term
function countHardCoursesInTerm(term: CourseRequirement[]): number {
  return term.filter(c => getCourseDifficulty(c) === 'hard').length;
}

// Get subject distribution in a term
function getSubjectDistribution(term: CourseRequirement[]): Record<string, number> {
  const dist: Record<string, number> = {};
  for (const course of term) {
    const subject = getSubject(course.code);
    dist[subject] = (dist[subject] || 0) + 1;
  }
  return dist;
}

// Check if adding a course creates too much subject concentration (prevent 2+ of same subject)
function wouldCreateSubjectConcentration(term: CourseRequirement[], newCourse: CourseRequirement): boolean {
  const dist = getSubjectDistribution(term);
  const newSubject = getSubject(newCourse.code);
  const newCount = (dist[newSubject] || 0) + 1;
  
  // Avoid 2+ of same subject in one term (aggressive diversity)
  return newCount >= 2;
}

// Calculate how many unique subjects are in a term
function getUniqueSubjectCount(term: CourseRequirement[]): number {
  const subjects = new Set(term.map(c => getSubject(c.code)));
  return subjects.size;
}

// Score a candidate for a term (lower is better - more balanced)
function scoreTermCandidateBalance(term: CourseRequirement[], candidate: CourseRequirement, availableCourses: CourseRequirement[]): number {
  let score = 0;
  const candidateSubject = getSubject(candidate.code);
  const currentSubjects = getSubjectDistribution(term);
  const subjectCount = Object.keys(currentSubjects).length;
  
  // PRIMARY: Hard constraint - enforce prerequisites (already filtered, but reflected in scoring)
  // If we're here, prerequisites are met
  
  // SECONDARY: Subject diversity is paramount - large bonus for new subjects
  if (!currentSubjects[candidateSubject]) {
    // Brand new subject - big bonus (negative score = better)
    score -= 1000;
  } else {
    // Repeated subject - big penalty
    score += 500;
  }
  
  // TERTIARY: Balance difficulty
  const difficulty = getCourseDifficulty(candidate);
  const hardCount = countHardCoursesInTerm(term);
  
  if (difficulty === 'hard' && hardCount >= 2) {
    score += 300; // Strong penalty for too many hard courses
  } else if (difficulty === 'hard') {
    score -= 50; // Slight bonus for hard courses if we have room
  } else if (difficulty === 'medium') {
    score -= 30; // Small bonus for balance
  }
  
  // QUATERNARY: Course priority
  score -= priorityValue(candidate.priority) * 5;
  
  // Tiebreaker: prefer courses that appear earlier in available list (stable)
  const positionInAvailable = availableCourses.findIndex(c => c.code === candidate.code);
  if (positionInAvailable >= 0) {
    score += positionInAvailable * 0.1;
  }
  
  return score;
}

// Improved sequence building with balance considerations
function buildSequence(
  missing: CourseRequirement[],
  completedCodes: Set<string>,
  rawInputs: string[]
) {
  const remaining = [...missing];
  const plannedCodes = new Set(completedCodes);
  const terms: CourseRequirement[][] = [];
  const MAX_COURSES_PER_TERM = 4;
  const MAX_HARD_COURSES_PER_TERM = 2;

  for (let term = 0; term < 4 && remaining.length > 0; term++) {
    const currentTerm: CourseRequirement[] = [];
    const available = remaining
      .filter((course) => prerequisitesMet(course, plannedCodes, rawInputs));

    if (available.length === 0) break;

    // Build term by selecting balanced courses
    let maxCourses = Math.min(3 + (term === 0 ? 1 : 0), MAX_COURSES_PER_TERM); // First term can have 4
    
    while (currentTerm.length < maxCourses && available.length > 0) {
      let bestIdx = -1;
      let bestScore = Infinity;
      const currentSubjects = getSubjectDistribution(currentTerm);

      // Phase 1: Try to add courses from NEW subjects first (hard requirement)
      for (let i = 0; i < available.length; i++) {
        const course = available[i];
        const courseSubject = getSubject(course.code);
        
        // Skip hard courses if we're already at limit
        if (getCourseDifficulty(course) === 'hard' && 
            countHardCoursesInTerm(currentTerm) >= MAX_HARD_COURSES_PER_TERM &&
            available.length > 1) {
          continue;
        }

        // Prioritize: NEW subject (not yet in term)
        if (!currentSubjects[courseSubject]) {
          const score = scoreTermCandidateBalance(currentTerm, course, available);
          if (score < bestScore) {
            bestScore = score;
            bestIdx = i;
          }
        }
      }

      // Phase 2: If no new subjects, take from least-represented subjects
      if (bestIdx === -1) {
        for (let i = 0; i < available.length; i++) {
          const course = available[i];
          const courseSubject = getSubject(course.code);
          
          // Skip hard courses if we're already at limit
          if (getCourseDifficulty(course) === 'hard' && 
              countHardCoursesInTerm(currentTerm) >= MAX_HARD_COURSES_PER_TERM &&
              available.length > 1) {
            continue;
          }

          const score = scoreTermCandidateBalance(currentTerm, course, available);
          
          if (score < bestScore) {
            bestScore = score;
            bestIdx = i;
          }
        }
      }

      // Phase 3: Last resort - just take highest priority
      if (bestIdx === -1) {
        bestIdx = available.findIndex(c => c.priority === 'High') ?? 0;
        if (bestIdx === -1) bestIdx = 0;
      }

      const selected = available.splice(bestIdx, 1)[0];
      currentTerm.push(selected);
      plannedCodes.add(selected.code);
      
      const idx = remaining.findIndex(c => c.code === selected.code);
      if (idx !== -1) remaining.splice(idx, 1);
    }

    if (currentTerm.length > 0) {
      terms.push(currentTerm);
    }
  }

  return terms;
}

// Format course display, avoiding duplicates
function formatCourseDisplay(course: CourseRequirement): string {
  const codeNorm = normalize(course.code);
  const nameNorm = normalize(course.name);
  
  // If code and name are essentially the same (normalized), show only once
  if (codeNorm === nameNorm) {
    return course.code;
  }
  
  // Otherwise show both
  return `${course.code} — ${course.name}`;
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

// ── Static data ────────────────────────────────────────────────────────────

const UC_STATS: Record<string, { rate: string; gpa: string; tag: boolean; tagGPA?: string }> = {
  "UCLA":              { rate: "22.7%", gpa: "3.5–3.9", tag: false },
  "UC Berkeley":       { rate: "24%",   gpa: "3.5–3.9", tag: false },
  "UC San Diego":      { rate: "52.7%", gpa: "3.55–3.94", tag: false },
  "UC Irvine":         { rate: "39.5%", gpa: "3.4–3.7", tag: true,  tagGPA: "3.4" },
  "UC Santa Barbara":  { rate: "58.9%", gpa: "3.4–3.7", tag: true,  tagGPA: "3.2" },
  "UC Davis":          { rate: "57%",   gpa: "3.4–3.7", tag: true,  tagGPA: "3.2" },
  "UC Santa Cruz":     { rate: "68.8%", gpa: "3.3–3.6", tag: true,  tagGPA: "2.8" },
  "UC Riverside":      { rate: "68.2%", gpa: "3.0–3.5", tag: true,  tagGPA: "2.8" },
  "UC Merced":         { rate: "72.1%", gpa: "3.0–3.4", tag: true,  tagGPA: "2.4" },
};

const IGETC_AREAS = [
  { id: "1a", area: "1A", title: "English Composition", detail: "1 course (e.g. English 1A)" },
  { id: "1b", area: "1B", title: "Critical Thinking / Composition", detail: "1 course" },
  { id: "1c", area: "1C", title: "Oral Communication", detail: "1 course (CSU only)" },
  { id: "2",  area: "2",  title: "Mathematical Concepts", detail: "1 course (e.g. Calc, Stats)" },
  { id: "3a", area: "3A", title: "Arts",       detail: "1 course minimum" },
  { id: "3b", area: "3B", title: "Humanities",  detail: "1 course minimum" },
  { id: "4",  area: "4",  title: "Social & Behavioral Sciences", detail: "3 courses, 2+ disciplines" },
  { id: "5a", area: "5A", title: "Physical Sciences", detail: "1 course" },
  { id: "5b", area: "5B", title: "Biological Sciences", detail: "1 course" },
  { id: "5c", area: "5C", title: "Lab Science",  detail: "1 lab (can overlap 5A or 5B)" },
  { id: "6",  area: "6",  title: "Language Other Than English", detail: "2 years HS or 1 college course" },
];

const DEADLINES = [
  { label: "TAG Application",     date: "Sept 1–30",   note: "Applies to UC Davis, Irvine, Merced, Riverside, UCSB, UCSC" },
  { label: "UC Application",      date: "Nov 1–30",    note: "Apply at apply.universityofcalifornia.edu" },
  { label: "FAFSA / CADAA Opens", date: "Oct 1",       note: "Apply early — CA Dream Act for undocumented students" },
  { label: "Cal Grant Deadline",  date: "March 2",     note: "Must file FAFSA/CADAA by this date" },
  { label: "Transfer Decision",   date: "April–May",   note: "UCs typically notify transfer applicants" },
  { label: "SIR Deadline",        date: "June 1",      note: "Statement of Intent to Register at your chosen UC" },
];

// ── Markdown renderer ───────────────────────────────────────────────────────

function renderInline(text: string): ReactNode {
  const parts = text.split(/(\*\*.*?\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i}>{p.slice(2, -2)}</strong>
      : p
  );
}

function SimpleMarkdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let listBuf: string[] = [];

  function flush() {
    if (!listBuf.length) return;
    out.push(
      <ul key={out.length} className="my-2 space-y-1 pl-5 list-disc">
        {listBuf.map((li, i) => <li key={i} className="text-sm leading-6">{renderInline(li)}</li>)}
      </ul>
    );
    listBuf = [];
  }

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^###\s/.test(line)) {
      flush();
      out.push(<h4 key={out.length} className="mt-4 mb-1 font-bold text-[#303236]">{line.slice(4)}</h4>);
    } else if (/^##\s/.test(line)) {
      flush();
      out.push(<h3 key={out.length} className="mt-5 mb-1 text-base font-bold text-[#0b7f46]">{line.slice(3)}</h3>);
    } else if (/^#\s/.test(line)) {
      flush();
      out.push(<h2 key={out.length} className="mt-5 mb-2 text-lg font-bold text-[#303236]">{line.slice(2)}</h2>);
    } else if (/^[\*\-]\s/.test(line)) {
      listBuf.push(line.slice(2));
    } else if (line.trim() === "") {
      flush();
    } else {
      flush();
      out.push(<p key={out.length} className="my-1 text-sm leading-6">{renderInline(line)}</p>);
    }
  }
  flush();
  return <div>{out}</div>;
}

// ── UC Stats Panel ──────────────────────────────────────────────────────────

function UCStatsPanel({ school }: { school: string }) {
  const s = UC_STATS[school];
  if (!s) return null;
  const rateNum = parseFloat(s.rate);
  const color = rateNum < 30 ? "text-red-600" : rateNum < 55 ? "text-yellow-600" : "text-green-600";
  const label = rateNum < 30 ? "Very Selective" : rateNum < 55 ? "Selective" : "Accessible";
  return (
    <div className="mt-4 rounded-2xl border border-[#d8d0c3] bg-white p-4">
      <p className="text-xs font-bold uppercase tracking-widest text-[#7b818b] mb-3">{school} — Admission Stats</p>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="rounded-xl border border-[#d8d0c3] bg-[#faf8f3] p-3">
          <p className={`text-xl font-bold ${color}`}>{s.rate}</p>
          <p className="text-xs text-[#7b818b] mt-1">Transfer admit rate</p>
        </div>
        <div className="rounded-xl border border-[#d8d0c3] bg-[#faf8f3] p-3">
          <p className="text-xl font-bold text-[#303236]">{s.gpa}</p>
          <p className="text-xs text-[#7b818b] mt-1">Avg transfer GPA</p>
        </div>
        <div className="rounded-xl border border-[#d8d0c3] bg-[#faf8f3] p-3">
          <p className={`text-xl font-bold ${s.tag ? "text-green-600" : "text-red-500"}`}>{s.tag ? "✓ TAG" : "✗ TAG"}</p>
          <p className="text-xs text-[#7b818b] mt-1">{s.tag ? `Min GPA ${s.tagGPA}` : "No TAG offered"}</p>
        </div>
      </div>
      <p className={`mt-3 text-xs font-semibold ${color}`}>{label} — Aim for 3.0+ minimum (3.5+ for selective campuses). UC eligibility floor is 2.4 but far from competitive.</p>
    </div>
  );
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

  // ── Transfer AI chat ──────────────────────────────────────────
  const [chatOpen, setChatOpen] = useState(false);

  // ── Wizard onboarding ─────────────────────────────────────────
  const [wizardStep, setWizardStep] = useState<1|2|3|4>(1);
  const [wizardCollege, setWizardCollege] = useState("");
  const [wizardUCs, setWizardUCs] = useState<string[]>([]);
  const [wizardMajor, setWizardMajor] = useState("");
  const [wizardCourses, setWizardCourses] = useState("");
  const [wizardNoCourses, setWizardNoCourses] = useState(false);
  // ── Multi-school tabs ─────────────────────────────────────────
  const [planSchools, setPlanSchools] = useState<string[]>([]);
  const [activeSchoolTab, setActiveSchoolTab] = useState("");
  const [chatMode, setChatMode] = useState<"onboarding" | "advisor">("onboarding");
  const [chatMessages, setChatMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [onboardingDone, setOnboardingDone] = useState(false);
  const [aiPlan, setAiPlan] = useState("");
  const [aiPlanLoading, setAiPlanLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const onboardingStarted = useRef(false);

  // ── IGETC + tracker + panels ──────────────────────────────────
  const [igetcChecked, setIgetcChecked] = useState<Record<string, boolean>>({});
  const [trackerCourses, setTrackerCourses] = useState<{id:string;name:string;status:"planned"|"in-progress"|"done"}[]>([]);
  const [trackerInput, setTrackerInput] = useState("");
  const [showIgetc, setShowIgetc] = useState(false);
  const [showTracker, setShowTracker] = useState(false);
  const [showDeadlines, setShowDeadlines] = useState(false);
  const [showTagChecker, setShowTagChecker] = useState(false);

  useEffect(() => {
    if (chatOpen) chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, chatOpen]);

  // Persist IGETC and tracker to localStorage
  useEffect(() => {
    try { localStorage.setItem("igetc", JSON.stringify(igetcChecked)); } catch {}
  }, [igetcChecked]);
  useEffect(() => {
    try { localStorage.setItem("tracker", JSON.stringify(trackerCourses)); } catch {}
  }, [trackerCourses]);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("igetc");
      if (saved) setIgetcChecked(JSON.parse(saved));
      const saved2 = localStorage.getItem("tracker");
      if (saved2) setTrackerCourses(JSON.parse(saved2));
    } catch {}
  }, []);

  // Parse |||JSON{...}||| blocks from AI onboarding responses
  function parseOnboardingJSON(text: string): { college: string; targetSchool: string; major: string; completedCourses: string; ready: boolean } | null {
    const match = text.match(/\|\|\|JSON(\{[\s\S]*?\})\|\|\|/);
    if (!match) return null;
    try { return JSON.parse(match[1]); } catch { return null; }
  }

  // Strip the JSON block from displayed message
  function cleanMessage(text: string): string {
    return text.replace(/\|\|\|JSON\{[\s\S]*?\}\|\|\|/, "").trim();
  }

  const plannerContext = useMemo(() => ({
    college:          communityCollege,
    targetUniversity: targetSchool,
    major:            targetMajor,
    completedCourses: result?.completed ?? [],
    missingCourses:   result?.missing ?? [],
    blockedCourses:   result?.blocked ?? [],
    readinessScore:   result?.readinessScore ?? null,
  }), [communityCollege, targetSchool, targetMajor, result]);

  const streamResponse = useCallback(async (endpoint: string, history: { role: string; content: string }[], onChunk: (reply: string) => void) => {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history, plannerContext }),
    });
    if (!res.ok || !res.body) throw new Error("Failed");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let reply = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const lines = decoder.decode(value).split("\n");
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);
        if (data === "[DONE]") break;
        try { reply += JSON.parse(data); onChunk(reply); } catch {}
      }
    }
    return reply;
  }, [plannerContext]);

  const runOnboardingMessage = useCallback(async (history: { role: "user" | "assistant"; content: string }[]) => {
    setChatLoading(true);
    let reply = "";
    try {
      const tempMessages = [...history, { role: "assistant" as const, content: "" }];
      setChatMessages(tempMessages);
      reply = await streamResponse("/api/onboard", history, (r) => {
        setChatMessages([...history, { role: "assistant", content: cleanMessage(r) }]);
      });
      const parsed = parseOnboardingJSON(reply);
      if (parsed) {
        if (parsed.college) setCommunityCollege(parsed.college);
        if (parsed.targetSchool) setTargetSchool(parsed.targetSchool);
        if (parsed.major) setTargetMajor(parsed.major);
        if (parsed.completedCourses) setCompletedCourses(parsed.completedCourses);
        if (parsed.ready) {
          setOnboardingDone(true);
          setChatMode("advisor");
          setTimeout(() => {
            const btn = document.querySelector<HTMLButtonElement>('[data-generate-plan]');
            btn?.click();
          }, 500);
        }
      }
      setChatMessages([...history, { role: "assistant", content: cleanMessage(reply) }]);
    } catch {
      setChatMessages([...history, { role: "assistant", content: "Something went wrong. Please try again." }]);
    } finally {
      setChatLoading(false);
    }
  }, [streamResponse]);

  // Auto-start chat onboarding only if wizard was skipped and chat re-opened
  useEffect(() => {
    if (chatOpen && !onboardingStarted.current && chatMessages.length === 0 && !onboardingDone) {
      onboardingStarted.current = true;
      runOnboardingMessage([]);
    }
  }, [chatOpen, chatMessages.length, runOnboardingMessage, onboardingDone]);

  async function generateAIPlan(college: string, school: string, major: string, courses: string) {
    setAiPlanLoading(true);
    setAiPlan("");
    const completedList = courses.trim() ? courses : "none";
    const message = `You are building a 2-year semester-by-semester transfer schedule for a student at ${college} planning to transfer to ${school} for ${major}.

Already completed courses (DO NOT include these anywhere in the schedule): ${completedList}

Output format — use exactly these headers, nothing before them:
## Term 1 (Fall)
- COURSE# — Full Course Title as listed at ${college} (X units)

## Term 2 (Spring)
- COURSE# — Full Course Title as listed at ${college} (X units)

## Term 3 (Fall)
- COURSE# — Full Course Title as listed at ${college} (X units)

## Term 4 (Spring)
- COURSE# — Full Course Title as listed at ${college} (X units)

Example of correct format: "MATH 16A — Calculus for Business and Social Science (4 units)"

CRITICAL: Every course listed must be a course offered at ${college}, not at ${school}. The student takes classes at ${college} — these community college courses articulate to satisfy ${school} requirements. Never list a ${school} course number. Only list courses the student would actually enroll in at ${college}.

## Key Notes
- TAG: [eligible or not and why]
- IGETC: [complete or partial]
- GPA target: [number]

STRICT RULES — violating any of these is an error:

1. PREREQUISITES: Never place a course and its prerequisite in the same term. If course B requires course A, course A MUST appear in an earlier term. Example: MATH 16A and MATH 16B can NEVER be in the same term — 16A must come first.

2. COMPLETED COURSES: Do not list any course the student already completed. They are done. They do not appear anywhere in the schedule.

3. BALANCE: Each term must have a mix of subject areas — do not stack all math or all econ courses in one term. Spread prerequisites across terms naturally.

4. LOAD: 4–5 courses per term (13–17 units). Do not exceed this.

5. COURSE NUMBERS: Only use a specific course number (e.g. MATH 16A) if you have verified ASSIST articulation data for ${college}. If uncertain, write the requirement name only (e.g. "Microeconomics — verify on ASSIST.org").

6. NO PREAMBLE: Start your response directly with "## Term 1 (Fall)". No greeting, no intro paragraph.`;
    try {
      await streamResponse("/api/chat", [{ role: "user", content: message }], (r) => {
        // Strip the model-switch notice from the displayed output
        const cleaned = r.replace(/\[Note: switching to faster model[^\]]*\]/g, "").trimStart();
        setAiPlan(cleaned);
      });
    } catch {
      setAiPlan("Something went wrong generating your plan. Try asking the AI chat directly.");
    } finally {
      setAiPlanLoading(false);
    }
  }

  function completeWizard() {
    const courses = wizardNoCourses ? "" : wizardCourses;
    if (wizardCollege)    setCommunityCollege(wizardCollege);
    if (wizardUCs.length) setTargetSchool(wizardUCs[0]);
    if (wizardMajor)      setTargetMajor(wizardMajor);
    setCompletedCourses(courses);
    setPlanSchools(wizardUCs);
    setActiveSchoolTab(wizardUCs[0] ?? "");
    setOnboardingDone(true);
    setTimeout(() => {
      document.getElementById("planner")?.scrollIntoView({ behavior: "smooth" });
    }, 100);
    generateAIPlan(wizardCollege, wizardUCs[0] ?? "", wizardMajor, courses);
  }

  const sendChatMessage = useCallback(async (text?: string) => {
    const message = (text ?? chatInput).trim();
    if (!message || chatLoading) return;
    setChatInput("");
    const newHistory = [...chatMessages, { role: "user" as const, content: message }];
    setChatMessages(newHistory);

    if (chatMode === "onboarding" && !onboardingDone) {
      await runOnboardingMessage(newHistory);
      return;
    }

    setChatLoading(true);
    try {
      setChatMessages([...newHistory, { role: "assistant", content: "" }]);
      const reply = await streamResponse("/api/chat", newHistory.map(m => ({ ...m, content: m.content })), (r) => {
        setChatMessages([...newHistory, { role: "assistant", content: r.replace(/\[Note: switching to faster model[^\]]*\]/g, "").trimStart() }]);
      });
      setChatMessages([...newHistory, { role: "assistant", content: reply.replace(/\[Note: switching to faster model[^\]]*\]/g, "").trimStart() }]);
    } catch {
      setChatMessages([...newHistory, { role: "assistant", content: "Something went wrong. Please try again." }]);
    } finally {
      setChatLoading(false);
    }
  }, [chatInput, chatMessages, chatLoading, chatMode, onboardingDone, runOnboardingMessage, streamResponse]);

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
        setCommunityCollege("");
        setTargetSchool("");
        setTargetMajor("");
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

    // Defensive fallback: ensure uncertainMatches is an array
    const safeUncertainMatches = Array.isArray(uncertainMatches) ? uncertainMatches : [];
    const uncertaintyWarning = safeUncertainMatches.length
      ? `Some completed courses were ambiguous or could not be resolved exactly: ${safeUncertainMatches
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
        "Course sequence is an estimate based on available articulation/prerequisite data. Prerequisites and sequencing rules may be incomplete or not fully verified.",
        "Confirm all prerequisite requirements, unit limits, course availability, and transfer credits with ASSIST.org and a counselor before registering.",
        "The recommended sequence balances course difficulty and subject distribution, but actual enrollment may vary based on course availability, your schedule, and counselor guidance.",
        "GE filler classes are not major requirements. Use them only to balance your schedule.",
        uncertaintyWarning,
      ]
        .filter(Boolean)
        .join(' '),
    });
  }

  return (
    <main className="min-h-screen bg-[#eee9df] text-[#2f3135]">
      <section className="mx-auto max-w-7xl px-5 py-6 md:px-8">
        <nav className="mb-8 flex items-center justify-between border-b border-[#d8d0c3] pb-4 gap-4 flex-wrap bg-[#eee9df]">
          <div className="flex items-center gap-3 min-w-0">
            <img
              src="/coursebridge-logo.png"
              alt="CourseBridge logo"
              className="h-[80px] w-auto shrink-0"
              style={{mixBlendMode:"multiply"}}
            />
          </div>

          <a
            href="#planner"
            className="rounded-xl bg-[#0b7f46] px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[#08683a] shrink-0"
          >
            Build your plan
          </a>
        </nav>

        <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr]">
          <section className="pt-4">
            <p className="mb-4 inline-flex rounded-full border border-[#b8d8c7] bg-[#e7f3ed] px-4 py-2 text-sm font-semibold text-[#0b7f46]">
              Built around real transfer planning problems
            </p>

            <h1
              className="max-w-3xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl md:text-5xl lg:text-6xl"
              style={{background:"linear-gradient(135deg,#1a2e22 0%,#0b7f46 65%,#0fa85a 100%)",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text"}}
            >
              Know exactly what classes you need before you transfer.
            </h1>

            <p className="mt-5 max-w-2xl text-lg leading-8 text-[#6f7680]">
              CourseBridge helps community college students plan UC
              transfer requirements using real ASSIST data — personalized to
              your college, major, and target campus.
            </p>

            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <a
                href="#planner"
                className="rounded-xl bg-[#0b7f46] px-5 py-3 text-center font-semibold text-white shadow-sm transition hover:bg-[#08683a] hover:shadow-md"
              >
                Build My Transfer Plan
              </a>

              <a
                href="#example"
                className="rounded-xl border border-[#d1c7b8] bg-[#faf8f3] px-5 py-3 text-center font-semibold text-[#303236] transition hover:bg-white hover:border-[#0b7f46]"
              >
                See Example Plan
              </a>
            </div>

            <div className="mt-10 flex flex-wrap gap-8 border-t border-[#d8d0c3] pt-7">
              {[
                { n: "116", label: "Community Colleges" },
                { n: "57K+", label: "Courses indexed" },
                { n: "9", label: "UC campuses" },
                { n: "121K+", label: "Articulation agreements" },
              ].map(s => (
                <div key={s.label}>
                  <p className="text-2xl font-bold text-[#0b7f46]">{s.n}</p>
                  <p className="text-xs text-[#7b818b] mt-0.5">{s.label}</p>
                </div>
              ))}
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

          <Step number="2" title="Pick a UC and major">
            Choose the UC campus and major you want to transfer into.
          </Step>

          <Step number="3" title="Get a clear plan">
            See major requirements, blocked classes, and lighter GE filler
            options.
          </Step>
        </section>

        {/* ── School tabs ─────────────────────────────────────── */}
        {planSchools.length > 1 && (
          <div className="mt-16 rounded-2xl border border-[#d8d0c3] bg-white px-5 py-4 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-widest text-[#7b818b] mb-3">Your target schools</p>
            <div className="flex flex-wrap gap-2">
              {planSchools.map(school => (
                <button key={school}
                  onClick={() => {
                    setTargetSchool(school);
                    setActiveSchoolTab(school);
                    setResult(null);
                    generateAIPlan(communityCollege, school, targetMajor, completedCourses);
                  }}
                  className={`rounded-full border px-4 py-2 text-sm font-semibold transition shadow-sm ${activeSchoolTab === school ? "border-[#0b7f46] bg-[#0b7f46] text-white shadow-[#0b7f46]/20" : "border-[#d8d0c3] bg-[#faf8f3] text-[#4d535c] hover:border-[#0b7f46] hover:bg-[#f0faf5] hover:text-[#0b7f46]"}`}>
                  {school}
                </button>
              ))}
            </div>
          </div>
        )}

        <section
          id="planner"
          className={`${planSchools.length > 1 ? "mt-4" : "mt-16"} grid gap-6 lg:grid-cols-[0.72fr_1.28fr]`}
        >
          {/* Left panel: summary after wizard, form before */}
          <div className="rounded-3xl border border-[#d8d0c3] bg-[#faf8f3] shadow-[0_18px_45px_rgba(67,54,36,0.08)] overflow-hidden">
            {onboardingDone ? (
              <div className="flex flex-col">
                {/* Green gradient header */}
                <div className="bg-gradient-to-br from-[#0a6e3d] to-[#0d9456] px-6 pt-6 pb-5">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-2xl bg-white/20 flex items-center justify-center text-white font-bold text-lg shrink-0">
                      {(communityCollege || "?").slice(0,1).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-white/60 uppercase tracking-widest">Your Profile</p>
                      <p className="text-base font-bold text-white truncate">{communityCollege || "—"}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(planSchools.length > 1 ? planSchools : [targetSchool]).filter(Boolean).map(s => (
                      <span key={s} className="rounded-full bg-white/20 px-3 py-1 text-xs font-semibold text-white">{s}</span>
                    ))}
                    {targetMajor && <span className="rounded-full bg-white/10 border border-white/20 px-3 py-1 text-xs text-white/80">{targetMajor}</span>}
                  </div>
                </div>
                <div className="p-5 flex flex-col gap-4">
                  <div className="space-y-2">
                    {[
                      { label: "Completed Courses", value: completedCourses || "None yet" },
                    ].map(({ label, value }) => (
                      <div key={label} className="rounded-2xl border border-[#d8d0c3] bg-white px-4 py-3">
                        <p className="text-xs font-semibold text-[#7b818b] mb-1">{label}</p>
                        <p className="text-sm text-[#303236] break-words">{value || "—"}</p>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => { setOnboardingDone(false); setWizardStep(1); setAiPlan(""); setPlanSchools([]); }}
                    className="w-full rounded-2xl border border-[#d8d0c3] bg-white px-4 py-3 text-sm font-semibold text-[#7b818b] transition hover:border-[#0b7f46] hover:text-[#0b7f46]"
                  >
                    Edit my info
                  </button>
                  <button
                    type="button"
                    data-generate-plan
                    onClick={checkTransferPlan}
                    className="hidden"
                  />
                </div>
              </div>
            ) : (
              <div className="p-6">
                <h2 className="text-3xl font-bold text-[#303236]">Build your plan</h2>
                <p className="mt-3 text-base leading-7 text-[#7b818b]">Major prep comes first.</p>
                <form className="mt-8 space-y-5">
                  <SelectField label="Current college" value={communityCollege} options={collegeOptions}
                    onChange={(value) => { setCommunityCollege(value); setTargetSchool(""); setTargetMajor(""); resetResults(); }} />
                  <SelectField label="Target university" value={targetSchool} options={schoolOptions}
                    onChange={(value) => { setTargetSchool(value); setTargetMajor(""); resetResults(); }} />
                  <SelectField label="Target major" value={targetMajor} options={majorOptions}
                    onChange={(value) => { setTargetMajor(value); resetResults(); }} />
                  <label className="block">
                    <span className="mb-2 block text-sm font-bold text-[#303236]">Completed courses</span>
                    <textarea value={completedCourses}
                      onChange={(e) => { setCompletedCourses(e.target.value); resetResults(); }}
                      className="min-h-40 w-full rounded-2xl border border-[#d1c7b8] bg-white px-4 py-3 text-sm text-[#303236] outline-none transition placeholder:text-[#a2a7af] focus:border-[#0b7f46] focus:ring-4 focus:ring-[#0b7f46]/10"
                      placeholder="Example: econ1, math110a, math130, cs111c" />
                  </label>
                  <button type="button" data-generate-plan onClick={checkTransferPlan}
                    className="w-full rounded-2xl bg-[#0b7f46] px-5 py-4 text-lg font-bold text-white shadow-sm transition hover:bg-[#08683a]">
                    Generate Plan
                  </button>
                </form>
              </div>
            )}
          </div>

          <div className="rounded-3xl border border-[#d8d0c3] bg-[#faf8f3] shadow-[0_18px_45px_rgba(67,54,36,0.08)] overflow-hidden">
            {/* AI-generated plan from Flask backend */}
            {(aiPlanLoading || aiPlan) && (
              <div className="print-plan">
                {/* Green gradient header */}
                <div className="bg-gradient-to-br from-[#0a6e3d] via-[#0b7f46] to-[#0d9456] px-6 pt-6 pb-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-bold uppercase tracking-widest text-white/60 mb-1">Transfer AI Plan</p>
                      <h3 className="text-xl font-bold text-white truncate">{activeSchoolTab || targetSchool || "Your UC"}</h3>
                      {targetMajor && <p className="text-sm text-white/75 mt-0.5">{targetMajor}</p>}
                    </div>
                    {aiPlan && !aiPlanLoading && (
                      <button
                        onClick={() => window.print()}
                        className="shrink-0 rounded-xl bg-white/20 hover:bg-white/30 px-3 py-2 text-xs font-semibold text-white transition print:hidden"
                      >
                        Print / PDF
                      </button>
                    )}
                  </div>
                  {aiPlanLoading && (
                    <div className="mt-3 flex items-center gap-1.5">
                      {[0, 150, 300].map(d => (
                        <div key={d} className="w-2 h-2 rounded-full bg-white/70 animate-bounce" style={{animationDelay:`${d}ms`}} />
                      ))}
                      <span className="ml-2 text-xs text-white/60">Building your plan…</span>
                    </div>
                  )}
                </div>
                <div className="p-6 space-y-4">
                  <div className="rounded-2xl border border-[#d8d0c3] bg-white p-4 text-sm text-[#303236]">
                    {aiPlan
                      ? <SimpleMarkdown text={aiPlan} />
                      : (
                        <div className="space-y-3 animate-pulse">
                          {[80,60,90,50,70].map((w,i) => (
                            <div key={i} className="h-3 rounded-full bg-[#e8e3da]" style={{width:`${w}%`}} />
                          ))}
                        </div>
                      )}
                  </div>
                  {aiPlan && activeSchoolTab && <UCStatsPanel school={activeSchoolTab} />}
                </div>
              </div>
            )}
            {!result && !aiPlan && !aiPlanLoading && (
              <div className="p-6"><EmptyDashboard /></div>
            )}

            {result?.error && (
              <div className="m-6 rounded-2xl border border-[#ef9a9a] bg-[#fff0f0] p-6">
                <h3 className="text-xl font-bold text-[#9b1c1c]">
                  {result.error}
                </h3>

                <p className="mt-2 text-[#7f1d1d]">{result.notes}</p>
              </div>
            )}

            {result && !result.error && (
              <div className="p-6">
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
                                {formatCourseDisplay(course)}
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

        {/* ── Extra tools (visible after onboarding) ────────────── */}
        {onboardingDone && (
          <div className="mt-10 space-y-4 print:hidden">

            {/* TAG Eligibility Checker */}
            <div className="rounded-2xl border border-[#d8d0c3] bg-white overflow-hidden">
              <button
                onClick={() => setShowTagChecker(v => !v)}
                className="w-full flex items-center justify-between px-5 py-4 text-left transition hover:bg-[#faf8f3]"
              >
                <div>
                  <span className="text-sm font-bold text-[#303236]">TAG Eligibility Checker</span>
                  <span className="ml-2 text-xs text-[#7b818b]">Transfer Admission Guarantee</span>
                </div>
                <span className="text-[#7b818b] text-lg">{showTagChecker ? "−" : "+"}</span>
              </button>
              {showTagChecker && (
                <div className="px-5 pb-5 space-y-3">
                  <p className="text-xs text-[#7b818b] leading-5">TAG guarantees admission if you meet the requirements. <strong>UCLA, UC Berkeley, and UCSD do NOT offer TAG.</strong></p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {Object.entries(UC_STATS).map(([uc, s]) => (
                      <div key={uc} className={`rounded-xl border p-3 text-center ${s.tag ? "border-green-200 bg-green-50" : "border-[#d8d0c3] bg-[#faf8f3] opacity-60"}`}>
                        <p className="text-xs font-bold text-[#303236]">{uc.replace("UC ", "UC ")}</p>
                        {s.tag
                          ? <><p className="mt-1 text-green-700 text-xs font-semibold">✓ TAG offered</p><p className="text-xs text-[#7b818b]">Min GPA: {s.tagGPA}</p></>
                          : <p className="mt-1 text-xs text-[#9b1c1c]">✗ No TAG</p>
                        }
                      </div>
                    ))}
                  </div>
                  <div className="rounded-xl bg-[#faf8f3] border border-[#d8d0c3] p-3">
                    <p className="text-xs font-bold text-[#303236] mb-1">TAG Requirements (all UCs)</p>
                    <ul className="text-xs text-[#6f7680] space-y-1 list-disc pl-4">
                      <li>Complete 60 semester transferable units by end of spring before transfer</li>
                      <li>Meet the campus minimum TAG GPA (see above)</li>
                      <li>Complete IGETC or campus GE pattern (varies by campus)</li>
                      <li>Apply via UC TAG portal: Sept 1–30 each year</li>
                    </ul>
                  </div>
                </div>
              )}
            </div>

            {/* IGETC Checklist */}
            <div className="rounded-2xl border border-[#d8d0c3] bg-white overflow-hidden">
              <button
                onClick={() => setShowIgetc(v => !v)}
                className="w-full flex items-center justify-between px-5 py-4 text-left transition hover:bg-[#faf8f3]"
              >
                <div>
                  <span className="text-sm font-bold text-[#303236]">IGETC Checklist</span>
                  <span className="ml-2 text-xs text-[#7b818b]">
                    {Object.values(igetcChecked).filter(Boolean).length}/{IGETC_AREAS.length} areas done
                  </span>
                </div>
                <span className="text-[#7b818b] text-lg">{showIgetc ? "−" : "+"}</span>
              </button>
              {showIgetc && (
                <div className="px-5 pb-5 space-y-2">
                  <p className="text-xs text-[#7b818b] mb-3">Check off each IGETC area as you complete it. Progress is saved in your browser.</p>
                  {IGETC_AREAS.map(area => (
                    <label key={area.id} className={`flex items-start gap-3 rounded-xl border px-4 py-3 cursor-pointer transition ${igetcChecked[area.id] ? "border-green-300 bg-green-50" : "border-[#d8d0c3] bg-[#faf8f3] hover:border-[#0b7f46]/40"}`}>
                      <input
                        type="checkbox"
                        checked={!!igetcChecked[area.id]}
                        onChange={e => setIgetcChecked(prev => ({ ...prev, [area.id]: e.target.checked }))}
                        className="mt-0.5 h-4 w-4 rounded accent-[#0b7f46]"
                      />
                      <div>
                        <p className="text-sm font-semibold text-[#303236]">Area {area.area} — {area.title}</p>
                        <p className="text-xs text-[#7b818b]">{area.detail}</p>
                      </div>
                    </label>
                  ))}
                  <div className="mt-3 h-2 rounded-full bg-[#e0d9cf] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-[#0b7f46] transition-all duration-300"
                      style={{ width: `${Math.round((Object.values(igetcChecked).filter(Boolean).length / IGETC_AREAS.length) * 100)}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Course Progress Tracker */}
            <div className="rounded-2xl border border-[#d8d0c3] bg-white overflow-hidden">
              <button
                onClick={() => setShowTracker(v => !v)}
                className="w-full flex items-center justify-between px-5 py-4 text-left transition hover:bg-[#faf8f3]"
              >
                <div>
                  <span className="text-sm font-bold text-[#303236]">Course Progress Tracker</span>
                  <span className="ml-2 text-xs text-[#7b818b]">
                    {trackerCourses.filter(c => c.status === "done").length} done · {trackerCourses.filter(c => c.status === "in-progress").length} in progress
                  </span>
                </div>
                <span className="text-[#7b818b] text-lg">{showTracker ? "−" : "+"}</span>
              </button>
              {showTracker && (
                <div className="px-5 pb-5 space-y-3">
                  <div className="flex gap-2">
                    <input
                      value={trackerInput}
                      onChange={e => setTrackerInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter" && trackerInput.trim()) {
                          setTrackerCourses(prev => [...prev, { id: Date.now().toString(), name: trackerInput.trim(), status: "planned" }]);
                          setTrackerInput("");
                        }
                      }}
                      placeholder="Add a course (e.g. MATH 1A)"
                      className="flex-1 rounded-xl border border-[#d1c7b8] bg-[#faf8f3] px-3 py-2 text-sm outline-none focus:border-[#0b7f46] focus:ring-2 focus:ring-[#0b7f46]/10"
                    />
                    <button
                      onClick={() => {
                        if (trackerInput.trim()) {
                          setTrackerCourses(prev => [...prev, { id: Date.now().toString(), name: trackerInput.trim(), status: "planned" }]);
                          setTrackerInput("");
                        }
                      }}
                      className="rounded-xl bg-[#0b7f46] px-4 py-2 text-sm font-bold text-white transition hover:bg-[#08683a]"
                    >Add</button>
                  </div>
                  {trackerCourses.length === 0 && (
                    <p className="text-xs text-[#a2a7af] text-center py-3">No courses added yet. Type a course name and press Enter.</p>
                  )}
                  <div className="space-y-2">
                    {trackerCourses.map(c => (
                      <div key={c.id} className="flex items-center gap-3 rounded-xl border border-[#d8d0c3] bg-[#faf8f3] px-3 py-2">
                        <p className="flex-1 text-sm text-[#303236]">{c.name}</p>
                        <select
                          value={c.status}
                          onChange={e => setTrackerCourses(prev => prev.map(x => x.id === c.id ? { ...x, status: e.target.value as "planned"|"in-progress"|"done" } : x))}
                          className={`rounded-lg border px-2 py-1 text-xs font-semibold outline-none ${c.status === "done" ? "border-green-300 bg-green-50 text-green-700" : c.status === "in-progress" ? "border-yellow-300 bg-yellow-50 text-yellow-700" : "border-[#d8d0c3] bg-white text-[#7b818b]"}`}
                        >
                          <option value="planned">Planned</option>
                          <option value="in-progress">In Progress</option>
                          <option value="done">Done</option>
                        </select>
                        <button
                          onClick={() => setTrackerCourses(prev => prev.filter(x => x.id !== c.id))}
                          className="text-xs text-[#c4b9aa] transition hover:text-[#9b1c1c]"
                        >✕</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Application Deadline Reminders */}
            <div className="rounded-2xl border border-[#d8d0c3] bg-white overflow-hidden">
              <button
                onClick={() => setShowDeadlines(v => !v)}
                className="w-full flex items-center justify-between px-5 py-4 text-left transition hover:bg-[#faf8f3]"
              >
                <div>
                  <span className="text-sm font-bold text-[#303236]">Application Deadline Reminders</span>
                  <span className="ml-2 text-xs text-[#7b818b]">TAG · UC App · FAFSA · more</span>
                </div>
                <span className="text-[#7b818b] text-lg">{showDeadlines ? "−" : "+"}</span>
              </button>
              {showDeadlines && (
                <div className="px-5 pb-5">
                  <div className="space-y-3">
                    {DEADLINES.map(d => (
                      <div key={d.label} className="flex items-start gap-4 rounded-xl border border-[#d8d0c3] bg-[#faf8f3] px-4 py-3">
                        <div className="min-w-[90px]">
                          <p className="text-xs font-bold text-[#0b7f46]">{d.date}</p>
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-[#303236]">{d.label}</p>
                          <p className="text-xs text-[#7b818b]">{d.note}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-xs text-[#a2a7af]">Dates are typical annual deadlines. Always confirm with the official UC and financial aid websites.</p>
                </div>
              )}
            </div>

          </div>
        )}

        <footer className="mt-10 border-t border-[#d8d0c3] pt-5 text-sm text-[#7b818b]">
          Demo data only. CourseBridge is independent and not affiliated with
          ASSIST, UC, CSU, or CCSF. Always verify requirements through
          ASSIST.org, official college catalogs, and a counselor.
        </footer>
      </section>

      {/* ── Step wizard onboarding ───────────────────────────── */}
      {!onboardingDone && (() => {
        const UC_OPTIONS = ["UCLA","UC Berkeley","UC San Diego","UC Irvine","UC Santa Barbara","UC Davis","UC Santa Cruz","UC Riverside","UC Merced"];
        const CC_SUGGESTIONS = ["De Anza College","Mt. SAC","Santa Monica College","Diablo Valley College","City College of SF","Foothill College","Pasadena City College","El Camino College","Irvine Valley College","Los Angeles Valley College","Cerritos College","Grossmont College","Palomar College","Saddleback College"];
        const MAJOR_SUGGESTIONS = ["Computer Science","Business Administration","Economics","Psychology","Biology","Nursing","Engineering","Political Science","Sociology","Mathematics","English","Data Science","Mechanical Engineering","Electrical Engineering","Chemistry","Kinesiology","Communications","Accounting","Architecture","Film & Media Studies"];
        const steps = ["College","Target UCs","Major","Courses"];
        const toggleUC = (uc: string) => setWizardUCs(prev => prev.includes(uc) ? prev.filter(u => u !== uc) : [...prev, uc]);
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="w-full max-w-lg rounded-3xl bg-white shadow-2xl overflow-hidden">

              {/* Green gradient header */}
              <div className="bg-gradient-to-br from-[#0a6e3d] to-[#0d9456] px-8 pt-7 pb-6">
                {/* Step circles */}
                <div className="flex items-center gap-2 mb-5">
                  {steps.map((label, i) => (
                    <div key={i} className="flex items-center gap-2 flex-1">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all duration-300 ${
                        i < wizardStep - 1 ? "bg-white text-[#0b7f46]" :
                        i === wizardStep - 1 ? "bg-white text-[#0b7f46] ring-4 ring-white/25" :
                        "bg-white/15 text-white/50"
                      }`}>
                        {i < wizardStep - 1 ? "✓" : i + 1}
                      </div>
                      <span className={`hidden sm:block text-xs font-semibold truncate transition-all duration-300 ${i === wizardStep - 1 ? "text-white" : "text-white/40"}`}>{label}</span>
                      {i < steps.length - 1 && (
                        <div className={`flex-1 h-0.5 rounded-full transition-all duration-300 ${i < wizardStep - 1 ? "bg-white/60" : "bg-white/20"}`} />
                      )}
                    </div>
                  ))}
                </div>
                <h2 className="text-2xl font-bold text-white">
                  {wizardStep === 1 ? "Where do you go to school?" :
                   wizardStep === 2 ? "Which UCs are you targeting?" :
                   wizardStep === 3 ? "What do you want to study?" :
                   "What courses have you completed?"}
                </h2>
                <p className="mt-1.5 text-sm text-white/70">
                  {wizardStep === 1 ? "Enter your California community college" :
                   wizardStep === 2 ? "Select all that apply — we'll build a plan for each" :
                   wizardStep === 3 ? "Enter your intended major" :
                   "List them in plain text — don't worry about formatting"}
                </p>
              </div>

              <div className="p-7">
                {/* Step 1 — College */}
                {wizardStep === 1 && (
                  <div className="flex flex-col gap-4">
                    <input
                      list="cc-list"
                      value={wizardCollege}
                      onChange={e => setWizardCollege(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter" && wizardCollege.trim()) setWizardStep(2); }}
                      placeholder="e.g. De Anza College"
                      className="w-full rounded-2xl border border-[#d1c7b8] bg-[#faf8f3] px-4 py-3 text-sm text-[#303236] outline-none transition focus:border-[#0b7f46] focus:ring-4 focus:ring-[#0b7f46]/10"
                      autoFocus
                    />
                    <datalist id="cc-list">
                      {CC_SUGGESTIONS.map(cc => <option key={cc} value={cc} />)}
                    </datalist>
                    <div className="flex flex-wrap gap-2">
                      {CC_SUGGESTIONS.slice(0,6).map(cc => (
                        <button key={cc} onClick={() => { setWizardCollege(cc); setWizardStep(2); }}
                          className="rounded-full border border-[#d8d0c3] bg-[#faf8f3] px-3 py-1 text-xs text-[#4d535c] transition hover:border-[#0b7f46] hover:bg-[#f0faf5] hover:text-[#0b7f46]">
                          {cc}
                        </button>
                      ))}
                    </div>
                    <div className="flex justify-end pt-2">
                      <button onClick={() => setWizardStep(2)} disabled={!wizardCollege.trim()}
                        className="rounded-2xl bg-[#0b7f46] px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#08683a] disabled:opacity-40">
                        Next →
                      </button>
                    </div>
                  </div>
                )}
                {/* Step 2 — Target UCs (multi-select) */}
                {wizardStep === 2 && (
                  <div className="flex flex-col gap-4">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {UC_OPTIONS.map(uc => (
                        <button key={uc} onClick={() => toggleUC(uc)}
                          className={`rounded-2xl border px-3 py-3 text-sm font-semibold transition ${wizardUCs.includes(uc) ? "border-[#0b7f46] bg-[#f0faf5] text-[#0b7f46]" : "border-[#d8d0c3] bg-[#faf8f3] text-[#303236] hover:border-[#0b7f46] hover:text-[#0b7f46]"}`}>
                          {wizardUCs.includes(uc) ? "✓ " : ""}{uc}
                        </button>
                      ))}
                    </div>
                    {wizardUCs.length > 0 && (
                      <p className="text-xs text-[#0b7f46] font-medium">{wizardUCs.length} school{wizardUCs.length > 1 ? "s" : ""} selected</p>
                    )}
                    <div className="flex justify-between items-center pt-2">
                      <button onClick={() => setWizardStep(1)} className="text-sm text-[#7b818b] transition hover:text-[#303236]">← Back</button>
                      <button onClick={() => setWizardStep(3)} disabled={wizardUCs.length === 0}
                        className="rounded-2xl bg-[#0b7f46] px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#08683a] disabled:opacity-40">
                        Next →
                      </button>
                    </div>
                  </div>
                )}
                {/* Step 3 — Major */}
                {wizardStep === 3 && (
                  <div className="flex flex-col gap-4">
                    <input
                      list="major-list"
                      value={wizardMajor}
                      onChange={e => setWizardMajor(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter" && wizardMajor.trim()) setWizardStep(4); }}
                      placeholder="e.g. Computer Science"
                      className="w-full rounded-2xl border border-[#d1c7b8] bg-[#faf8f3] px-4 py-3 text-sm text-[#303236] outline-none transition focus:border-[#0b7f46] focus:ring-4 focus:ring-[#0b7f46]/10"
                      autoFocus
                    />
                    <datalist id="major-list">
                      {MAJOR_SUGGESTIONS.map(m => <option key={m} value={m} />)}
                    </datalist>
                    <div className="flex flex-wrap gap-2">
                      {MAJOR_SUGGESTIONS.slice(0,8).map(m => (
                        <button key={m} onClick={() => { setWizardMajor(m); setWizardStep(4); }}
                          className="rounded-full border border-[#d8d0c3] bg-[#faf8f3] px-3 py-1 text-xs text-[#4d535c] transition hover:border-[#0b7f46] hover:bg-[#f0faf5] hover:text-[#0b7f46]">
                          {m}
                        </button>
                      ))}
                    </div>
                    <div className="flex justify-between items-center pt-2">
                      <button onClick={() => setWizardStep(2)} className="text-sm text-[#7b818b] transition hover:text-[#303236]">← Back</button>
                      <button onClick={() => setWizardStep(4)} disabled={!wizardMajor.trim()}
                        className="rounded-2xl bg-[#0b7f46] px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#08683a] disabled:opacity-40">
                        Next →
                      </button>
                    </div>
                  </div>
                )}
                {/* Step 4 — Courses */}
                {wizardStep === 4 && (
                  <div className="flex flex-col gap-4">
                    <label className="flex items-center gap-3 cursor-pointer select-none">
                      <input type="checkbox" checked={wizardNoCourses} onChange={e => { setWizardNoCourses(e.target.checked); if (e.target.checked) setWizardCourses(""); }}
                        className="w-4 h-4 rounded accent-[#0b7f46]" />
                      <span className="text-sm text-[#303236]">I haven't completed any classes yet</span>
                    </label>
                    {!wizardNoCourses && (
                      <textarea
                        value={wizardCourses}
                        onChange={e => setWizardCourses(e.target.value)}
                        placeholder="e.g. Calc 1, English 1A, Intro to CS, Econ 1"
                        rows={4}
                        className="w-full rounded-2xl border border-[#d1c7b8] bg-[#faf8f3] px-4 py-3 text-sm text-[#303236] outline-none transition focus:border-[#0b7f46] focus:ring-4 focus:ring-[#0b7f46]/10 resize-none"
                        autoFocus
                      />
                    )}
                    <div className="flex justify-between items-center pt-2">
                      <button onClick={() => setWizardStep(3)} className="text-sm text-[#7b818b] transition hover:text-[#303236]">← Back</button>
                      <button onClick={completeWizard} disabled={!wizardNoCourses && !wizardCourses.trim()}
                        className="rounded-2xl bg-[#0b7f46] px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#08683a] disabled:opacity-40">
                        Build My Plan →
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── Transfer AI floating chat ─────────────────────────── */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-[#0b7f46] px-5 py-4 text-base font-semibold text-white shadow-xl transition hover:bg-[#08683a] active:scale-95 sm:py-3 sm:text-sm"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          {onboardingDone ? "Ask Transfer AI" : "Build My Plan with AI"}
        </button>
      )}

      {chatOpen && (
        <div className={`fixed z-50 flex ${
          onboardingDone
            ? "inset-x-0 bottom-0 top-[8vh] sm:inset-auto sm:bottom-6 sm:right-6 sm:top-auto sm:items-end sm:justify-end pointer-events-none"
            : "inset-0 items-center justify-center bg-black/60 p-4"
        }`}>
          <div className={`pointer-events-auto flex flex-col bg-white shadow-2xl ${
            onboardingDone
              ? "w-full rounded-t-3xl border border-[#d8d0c3] sm:rounded-2xl sm:w-[460px] sm:h-[680px] h-full"
              : "w-full max-w-lg rounded-2xl border border-[#d8d0c3] h-[90vh] sm:h-[640px]"
          }`}>
            {/* Header */}
            <div className="flex items-center justify-between rounded-t-3xl sm:rounded-t-2xl bg-gradient-to-r from-[#0a6e3d] to-[#0d9456] px-5 py-4">
              <div>
                <p className="text-base font-bold text-white">Transfer AI</p>
                {communityCollege && targetSchool
                  ? <p className="text-xs text-white/80 mt-0.5">{communityCollege} → {targetSchool}{targetMajor ? ` · ${targetMajor}` : ""}</p>
                  : <p className="text-xs text-white/80 mt-0.5">{onboardingDone ? "Ask me anything about your transfer" : "Setting up your plan…"}</p>
                }
              </div>
              {onboardingDone ? (
                <button onClick={() => setChatOpen(false)} className="rounded-full p-2 text-white/80 transition hover:bg-white/20 hover:text-white">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              ) : (
                <button onClick={() => { setOnboardingDone(true); setChatOpen(false); }} className="rounded-full px-3 py-1.5 text-xs font-semibold text-white/80 transition hover:bg-white/20 hover:text-white">
                  Skip
                </button>
              )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-4 py-5 space-y-4">
              {chatMessages.length === 0 && chatLoading && (
                <div className="flex justify-start">
                  <div className="rounded-2xl border border-[#d8d0c3] bg-[#faf8f3] px-4 py-3 text-sm text-[#7b818b]">
                    <span className="animate-pulse">Transfer AI is thinking…</span>
                  </div>
                </div>
              )}
              {onboardingDone && chatMessages.length > 0 && (
                <div className="flex flex-wrap gap-2 pb-1">
                  {["What should I take next semester?", "How competitive is my GPA?", "Tell me about TAG"].map((q) => (
                    <button key={q} onClick={() => sendChatMessage(q)}
                      className="rounded-full border border-[#d8d0c3] bg-[#faf8f3] px-3 py-1.5 text-xs text-[#4d535c] transition hover:border-[#0b7f46] hover:text-[#0b7f46]">
                      {q}
                    </button>
                  ))}
                </div>
              )}
              {chatMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                    msg.role === "user"
                      ? "bg-[#0b7f46] text-white"
                      : "border border-[#d8d0c3] bg-[#faf8f3] text-[#303236]"
                  }`}>
                    {msg.content || (msg.role === "assistant" && chatLoading ? <span className="animate-pulse">…</span> : "")}
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div className="border-t border-[#d8d0c3] p-4">
              <div className="flex gap-3">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } }}
                  placeholder="Ask about your transfer plan…"
                  className="flex-1 rounded-2xl border border-[#d8d0c3] bg-[#faf8f3] px-4 py-3 text-base outline-none transition focus:border-[#0b7f46] focus:ring-2 focus:ring-[#0b7f46]/10"
                />
                <button
                  onClick={() => sendChatMessage()}
                  disabled={!chatInput.trim() || chatLoading}
                  className="rounded-2xl bg-[#0b7f46] px-4 py-3 text-white transition hover:bg-[#08683a] disabled:opacity-40"
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
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
