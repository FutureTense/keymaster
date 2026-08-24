---
name: submit-pr
description: >-
  Procedure for preparing and submitting pull requests in keymaster, enforcing
  the required PR template (.github/PULL_REQUEST_TEMPLATE.md), checklist
  validation, and quality gates.
---

# Pull Request Submission Guide for Keymaster

This skill provides step-by-step instructions for preparing, validating, and
submitting pull requests to the Keymaster repository.

## Pre-PR Quality Gates Checklist

Before creating a PR, ensure all verification steps pass locally:

1. **Format & Linting**:

   ```bash
   ruff check --fix .
   ruff format .
   mypy custom_components/keymaster
   ```

2. **Frontend Build & Tests (if frontend modified)**:

   ```bash
   yarn lint
   yarn test
   yarn build
   ```

3. **Integration Tests & Coverage**:

   ```bash
   pytest --cov=custom_components/keymaster --cov-report=term-missing
   ```

   - Ensure all tests pass and coverage remains **>= 80%**.

## Mandatory Pull Request Template

Every pull request description **MUST** follow the repository template located
at `.github/PULL_REQUEST_TEMPLATE.md`.

### Required Sections & Rules

1. **# Summary**:
   - Provide a concise summary of the change and which issue is fixed or
     linked.
   - Include relevant motivation and context.

2. **## Breaking change** *(Include ONLY if applicable; remove section if not
   a breaking change)*:
   - Clearly describe what breaks for existing users, why the change was made,
     and how users can update their configurations to make it work.

3. **## Proposed change**:
   - Describe the architectural and functional changes to communicate to
     maintainers why the PR should be accepted.

4. **## Type of change**:
   - Check **exactly one (1)** box from:
     - `- [ ] Dependency upgrade`
     - `- [ ] Bugfix (non-breaking change which fixes an issue)`
     - `- [ ] New feature (which adds functionality)`
     - `- [ ] Breaking change (fix/feature causing existing functionality to break)`
     - `- [ ] Code quality improvements to existing code or addition of tests`
   - *Note*: If changes require multiple boxes, split the work into separate
     PRs.

5. **## Additional information**:
   - Link related or closed issues:
     - `This PR fixes or closes issue: fixes #<issue_number>`
     - `This PR is related to issue: #<issue_number>`

## Template Format Reference

```markdown
# Summary
<!-- Summary of changes, motivation, and context -->

## Breaking change
<!-- Only include if breaking change, otherwise omit -->

## Proposed change
<!-- Big picture explanation of the changes -->

## Type of change
- [ ] Dependency upgrade
- [ ] Bugfix (non-breaking change which fixes an issue)
- [ ] New feature (which adds functionality)
- [ ] Breaking change (fix/feature causing existing functionality to break)
- [ ] Code quality improvements to existing code or addition of tests

## Additional information
- This PR fixes or closes issue: fixes #
- This PR is related to issue:
```
