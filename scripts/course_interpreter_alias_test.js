import assert from 'assert';
import { interpretCompletedCourses } from '../lib/courseInterpreter.js';

const sampleRequirements = {
  CCSF: {
    'UC Berkeley': {
      'Economics, B.A.': {
        requiredCourses: [
          {
            code: 'ECON 1',
            name: 'ECON 1',
            aliases: ['ECON1'],
            satisfiedBy: [['ECON 1', 'ECON 3']],
          },
          {
            code: 'MATH 51',
            name: 'MATH 51',
            aliases: ['MATH51'],
            satisfiedBy: [['MATH 110A']],
          },
          {
            code: 'MATH 52',
            name: 'MATH 52',
            aliases: ['MATH52'],
            satisfiedBy: [['MATH 110B']],
          },
          {
            code: 'STAT 2',
            name: 'STAT 2',
            aliases: ['STAT2'],
            satisfiedBy: [['STAT C1000']],
          },
        ],
      },
    },
  },
};

function matched(rawText) {
  return interpretCompletedCourses(rawText, sampleRequirements).matchedCourses;
}

assert.deepEqual(matched('calc 1'), ['MATH 110A']);
assert.deepEqual(matched('calculus one'), ['MATH 110A']);
assert.deepEqual(matched('math110a'), ['MATH 110A']);
assert.deepEqual(matched('MATH-110A'), ['MATH 110A']);
assert.deepEqual(matched('intro micro'), ['ECON 1']);
assert.deepEqual(matched('microeconomics'), ['ECON 1']);
assert.deepEqual(matched('econ 1'), ['ECON 1']);
assert.deepEqual(matched('intro macro'), ['ECON 2']);
assert.deepEqual(matched('macroeconomics'), ['ECON 2']);
assert.deepEqual(matched('econ 2'), ['ECON 2']);
assert.deepEqual(matched('stats'), ['STAT C1000']);

console.log('Course interpreter alias tests passed');
