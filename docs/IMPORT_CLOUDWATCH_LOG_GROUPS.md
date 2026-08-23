# Importing existing CloudWatch log groups

## When this is needed

The Lambda module now manages `aws_cloudwatch_log_group` resources for every Lambda function so that retention is explicitly set (`7` days in dev, `30` days in prod) instead of relying on the Lambda default of "never expire".

In environments where the Lambda functions have already been invoked, AWS has auto-created log groups such as:

```
/aws/lambda/<name_prefix>-<function_name>-<region_abbrev>-<environment>
```

The first `tofu apply` in such an environment will fail with `ResourceAlreadyExistsException` unless those groups are imported into OpenTofu/Terraform state first.

> Only use root-module `import` blocks when the target log groups already exist. If a fresh environment has no existing groups, omit or remove the regular-function `import` block and let OpenTofu create the groups on the first apply. Keep the trigger-function `import` blocks only if those groups already exist.

If a `tofu plan` or `tofu apply` with the `import` blocks fails because the remote object does not exist, but a later apply fails with `ResourceAlreadyExistsException`, Lambda has auto-created the log groups in the meantime. Restore the regular-function `import` block so OpenTofu adopts the existing groups instead of trying to recreate them.

## How to import

The import blocks live in the environment root configurations (`tofu/application/environments/dev/main.tf` and `tofu/application/environments/prod/main.tf`), not in the Lambda module, because OpenTofu only allows `import` blocks in the root module.

If your OpenTofu/Terraform version supports declarative imports, a single `tofu plan` followed by `tofu apply` from the environment directory will import the existing groups automatically. If you prefer manual imports (or the import blocks have already been removed after the first apply), use the `tofu import` commands below.

### Declarative import blocks

1. Change to the environment directory and plan the apply. The import blocks will record the intended imports.

   ```bash
   cd tofu/application/environments/dev   # or prod
   tofu plan -target=module.lambda
   ```

2. Apply. OpenTofu will import each existing group and then set retention.

   ```bash
   tofu apply -target=module.lambda
   ```

   Once the groups are imported, the `import` blocks can be removed from the environment's `main.tf`.

### Manual `tofu import`

1. Plan the apply from the environment directory and note which log groups the plan wants to create.

   ```bash
   cd tofu/application/environments/dev   # or prod
   tofu plan -target=module.lambda
   ```

2. For each existing log group, import it into state. The resource addresses follow the module's `for_each` keys:

   ```bash
   # App functions
   tofu import 'module.lambda.aws_cloudwatch_log_group.functions["<function-key>"]' \
     '/aws/lambda/<name_prefix>-<function-key>-<region_abbrev>-<environment>'

   # Cognito trigger functions
   tofu import 'module.lambda.aws_cloudwatch_log_group.trigger_functions["<function-key>"]' \
     '/aws/lambda/<name_prefix>-<function-key>-<region_abbrev>-<environment>'
   ```

   For example, in the `dev` environment with `name_prefix = "kernelworx"` and `region_abbrev = "ue1"`:

   ```bash
   tofu import 'module.lambda.aws_cloudwatch_log_group.functions["list-my-shares"]' \
     '/aws/lambda/kernelworx-list-my-shares-ue1-dev'

   tofu import 'module.lambda.aws_cloudwatch_log_group.trigger_functions["post-auth"]' \
     '/aws/lambda/kernelworx-post-auth-ue1-dev'
   ```

3. Re-run the plan. It should now show only the desired retention change (or no changes at all if retention already matches).

   ```bash
   tofu plan -target=module.lambda
   ```

4. Apply as usual.

## Function keys

The current app function keys are:

- `list-my-shares`
- `list-catalogs-in-use`
- `create-profile`
- `request-report`
- `unit-reporting`
- `list-unit-catalogs`
- `list-unit-campaign-catalogs`
- `campaign-operations`
- `delete-campaign-orders`
- `delete-profile-cascade`
- `update-account`
- `delete-account`
- `transfer-ownership`
- `request-qr-upload`
- `confirm-qr-upload`
- `generate-qr-code-presigned-url`
- `delete-qr-code`
- `validate-payment-method`
- `admin-operations`

The current Cognito trigger function keys are:

- `post-auth`
- `pre-signup`

> The exact set is defined in `tofu/application/modules/lambda/main.tf` under `local.functions` and `local.trigger_functions`. If those maps change, update this list and the corresponding `import` blocks in both environment root configurations.

## Scripted bulk import

If you have AWS CLI access and the functions already exist, you can generate the import commands for the current environment:

```bash
prefix="kernelworx"
region_abbrev="ue1"
environment="prod"   # change to "dev" as needed

for key in list-my-shares list-catalogs-in-use create-profile request-report unit-reporting \
           list-unit-catalogs list-unit-campaign-catalogs campaign-operations \
           delete-campaign-orders delete-profile-cascade update-account delete-account \
           transfer-ownership request-qr-upload confirm-qr-upload \
           generate-qr-code-presigned-url delete-qr-code validate-payment-method \
           admin-operations; do
  echo "tofu import 'module.lambda.aws_cloudwatch_log_group.functions[\"$key\"]' '/aws/lambda/$prefix-$key-$region_abbrev-$environment'"
done

for key in post-auth pre-signup; do
  echo "tofu import 'module.lambda.aws_cloudwatch_log_group.trigger_functions[\"$key\"]' '/aws/lambda/$prefix-$key-$region_abbrev-$environment'"
done
```

Copy the generated commands and run them from the appropriate environment directory (`tofu/application/environments/dev` or `tofu/application/environments/prod`).
