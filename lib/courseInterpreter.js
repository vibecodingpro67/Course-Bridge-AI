// Course interpreter utilities for completed-course recognition using deterministic aliases and fuzzy matching.
import { levenshtein, normalize } from './spellcheck.js';

const commonCourseAliases = {
  // Deterministic completed-course aliases. These return official CCSF codes
  // before plan generation; no AI/API calls are used here.
  'calc 1': 'MATH 110A',
  'calculus 1': 'MATH 110A',
  'calculus one': 'MATH 110A',
  'calc 2': 'MATH 110B',
  'calculus 2': 'MATH 110B',
  'calculus two': 'MATH 110B',
  'intro micro': 'ECON 1',
  'microeconomics': 'ECON 1',
  'econ 1': 'ECON 1',
  'intro macro': 'ECON 2',
  'macroeconomics': 'ECON 2',
  'econ 2': 'ECON 2',
  'stats': 'STAT C1000',
  'statistics': 'STAT C1000',
  'intro stats': 'STAT C1000',
};

function parseCompletedCourseInputs(rawText) {
  return String(rawText || '')
    .split(/[,;\n]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function normalizeAliasKey(value) {
  return normalize(String(value || ''));
}

function addAlias(aliasMap, alias, code) {
  const key = normalizeAliasKey(alias);
  if (!key) return;
  const existing = aliasMap.get(key);
  if (existing) {
    existing.add(code);
  } else {
    aliasMap.set(key, new Set([code]));
  }
}

function buildCourseAliasMap(assistRequirements) {
  const aliasMap = new Map();

  if (assistRequirements && typeof assistRequirements === 'object') {
    for (const fromCollege of Object.keys(assistRequirements)) {
      const targets = assistRequirements[fromCollege] || {};
      for (const target of Object.keys(targets)) {
        const majors = targets[target] || {};
        for (const major of Object.keys(majors)) {
          const majorData = majors[major] || {};
          const requiredCourses = Array.isArray(majorData.requiredCourses)
            ? majorData.requiredCourses
            : [];
          for (const course of requiredCourses) {
            addAlias(aliasMap, course.code, course.code);
            addAlias(aliasMap, course.name, course.code);
            if (Array.isArray(course.aliases)) {
              for (const alias of course.aliases) {
                addAlias(aliasMap, alias, course.code);
              }
            }

            if (Array.isArray(course.satisfiedBy)) {
              for (const option of course.satisfiedBy) {
                if (Array.isArray(option)) {
                  for (const code of option) {
                    if (typeof code !== 'string') continue;
                    addAlias(aliasMap, code, code);
                    addAlias(aliasMap, code.toLowerCase(), code);
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  for (const [alias, code] of Object.entries(commonCourseAliases)) {
    addAlias(aliasMap, alias, code);
  }

  return aliasMap;
}

function findExactMatch(inputKey, aliasMap) {
  return aliasMap.get(inputKey) || null;
}

function findFuzzyMatches(inputKey, aliasMap) {
  if (!inputKey) return null;
  let bestDistance = Infinity;
  const distances = new Map();

  for (const [key, codes] of aliasMap.entries()) {
    const distance = levenshtein(inputKey, key);
    if (distance > bestDistance + 2) continue;
    const existing = distances.get(distance);
    if (existing) {
      existing.push({ key, codes });
    } else {
      distances.set(distance, [{ key, codes }]);
    }
    bestDistance = Math.min(bestDistance, distance);
  }

  if (!Number.isFinite(bestDistance)) return null;

  const bestEntries = distances.get(bestDistance) || [];
  const codeSet = new Set();
  for (const entry of bestEntries) {
    for (const code of entry.codes) {
      codeSet.add(code);
    }
  }

  return {
    dist: bestDistance,
    candidates: Array.from(codeSet),
  };
}

function isFuzzyMatchAcceptable(inputKey, dist) {
  if (!inputKey) return false;
  const maxLen = Math.max(inputKey.length, 1);
  const ratio = dist / maxLen;
  if (dist === 0) return true;
  if (ratio <= 0.2) return true;
  return false;
}

// AI-assisted interpretation function
// Returns structured JSON with interpretation results
export function interpretWithAI(rawInput, validCourseCodesSet) {
  const cleanedInput = String(rawInput || '').trim();
  if (!cleanedInput) {
    return {
      success: false,
      interpretation: null,
      confidence: 'low',
      method: 'empty_input',
      alternatives: [],
      message: 'Empty input'
    };
  }

  // Convert the set to an array for filtering
  const validCourseCodes = Array.from(validCourseCodesSet);

  // Simple pattern matching for common course formats
  const coursePattern = /^([A-Z]{2,4})\s*(\d{3}[A-Z]?)$/i;
  const match = cleanedInput.match(coursePattern);

  if (match) {
    const [, dept, num] = match;
    const formattedCode = `${dept.toUpperCase()} ${num}`;

    // Check if this is in valid course codes
    if (validCourseCodes.includes(formattedCode)) {
      return {
        success: true,
        interpretation: formattedCode,
        confidence: 'high',
        method: 'pattern_matching',
        alternatives: [],
        message: ''
      };
    }

    // If not in valid codes but looks like a course, suggest similar valid codes
    const similarCodes = validCourseCodes
      .filter(code => code.startsWith(dept.toUpperCase()))
      .slice(0, 5);

    return {
      success: true,
      interpretation: null,
      confidence: 'low',
      method: 'pattern_matching',
      alternatives: similarCodes,
      message: `Did you mean one of these ${dept.toUpperCase()} courses?`
    };
  }

  // If we get here, no clear pattern match
  return {
    success: false,
    interpretation: null,
    confidence: 'low',
    method: 'no_pattern',
    alternatives: [],
    message: 'Please enter course in format like "MATH 110A" or use common aliases like "calc 1"'
  };
}

export function interpretCompletedCourses(rawText, assistRequirements) {
  const userInputs = parseCompletedCourseInputs(rawText);
  const aliasMap = buildCourseAliasMap(assistRequirements);
  const matchedCourses = new Set();
  const uncertainMatches = [];

  // Build a set of all valid course codes from the aliasMap
  const allValidCodesSet = new Set();
  for (const codes of aliasMap.values()) {
    for (const code of codes) {
      allValidCodesSet.add(code);
    }
  }

  for (const originalInput of userInputs) {
    const inputKey = normalizeAliasKey(originalInput);
    if (!inputKey) continue;

    let exactCodes = findExactMatch(inputKey, aliasMap);
    if (exactCodes) {
      if (exactCodes.size === 1) {
        matchedCourses.add(Array.from(exactCodes)[0]);
        continue;
      }
      // Multiple exact matches -> try AI to narrow down
      const aiResult = interpretWithAI(originalInput, exactCodes);
      if (aiResult.success && aiResult.confidence === 'high' && aiResult.interpretation && exactCodes.has(aiResult.interpretation)) {
        matchedCourses.add(aiResult.interpretation);
        continue;
      }
      // If AI didn't give a confident match in the exactCodes, then we treat as uncertain
      uncertainMatches.push({
        input: originalInput,
        possibleMatches: Array.from(exactCodes),
        message: `Which ${originalInput} course did you complete?`
      });
      continue;
    }

    let fuzzy = findFuzzyMatches(inputKey, aliasMap);
    if (fuzzy && isFuzzyMatchAcceptable(inputKey, fuzzy.dist)) {
      if (fuzzy.candidates.length === 1) {
        matchedCourses.add(fuzzy.candidates[0]);
        continue;
      }
      // Multiple fuzzy matches -> try AI to narrow down
      const aiResult = interpretWithAI(originalInput, new Set(fuzzy.candidates));
      if (aiResult.success && aiResult.confidence === 'high' && aiResult.interpretation && new Set(fuzzy.candidates).has(aiResult.interpretation)) {
        matchedCourses.add(aiResult.interpretation);
        continue;
      }
      uncertainMatches.push({
        input: originalInput,
        possibleMatches: fuzzy.candidates,
        message: `Which ${originalInput} course did you complete?`
      });
      continue;
    }

    // If we get here, no exact or acceptable fuzzy match
    if (fuzzy) {
      // We have a fuzzy match but not acceptable -> try AI with the fuzzy candidates
      const aiResult = interpretWithAI(originalInput, new Set(fuzzy.candidates));
      if (aiResult.success && aiResult.confidence === 'high' && aiResult.interpretation && new Set(fuzzy.candidates).has(aiResult.interpretation)) {
        matchedCourses.add(aiResult.interpretation);
        continue;
      }
      uncertainMatches.push({
        input: originalInput,
        possibleMatches: fuzzy.candidates,
        message: `Which ${originalInput} course did you complete?`
      });
      continue;
    } else {
      // No fuzzy match at all -> try AI with all valid codes
      const aiResult = interpretWithAI(originalInput, allValidCodesSet);
      if (aiResult.success && aiResult.confidence === 'high' && aiResult.interpretation && allValidCodesSet.has(aiResult.interpretation)) {
        matchedCourses.add(aiResult.interpretation);
        continue;
      }
      uncertainMatches.push({
        input: originalInput,
        possibleMatches: aiResult.alternatives || [],
        message: aiResult.message || `Which ${originalInput} course did you complete?`
      });
      continue;
    }
  }

  return {
    matchedCourses: Array.from(matchedCourses),
    uncertainMatches,
  };
}