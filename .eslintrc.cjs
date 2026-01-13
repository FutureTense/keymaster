module.exports = {
    env: {
        node: true
    },
    extends: [
        'eslint:recommended',
        'plugin:@typescript-eslint/recommended'
    ],
    overrides: [
        {
            files: ['*.ts', '*.tsx'],
            parserOptions: {
                project: ['./tsconfig.json']
            }
        },
        {
            files: ['**/*.test.ts'],
            rules: {
                'sort-keys': 'off'
            }
        }
    ],
    parser: '@typescript-eslint/parser',
    parserOptions: {
        ecmaVersion: 2023,
        project: true,
        sourceType: 'module'
    },
    plugins: [
        '@typescript-eslint'
    ],
    rules: {
        '@typescript-eslint/no-unused-vars': 'off',
        'sort-imports': [
            'error',
            {
                allowSeparatedGroups: true,
                ignoreCase: false,
                ignoreDeclarationSort: true,
                ignoreMemberSort: false,
                memberSyntaxSortOrder: ['none', 'all', 'multiple', 'single']
            }
        ]
    }
};
