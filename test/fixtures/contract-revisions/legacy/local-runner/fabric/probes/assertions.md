# Admission probe assertions

- The result validates against `capability-output.schema.json`.
- Every claimed fact has a resolvable evidence URI.
- The probe does not publish, message, charge, mutate production, or expose secrets.
- Timeout and cancellation return a typed partial or stopped result.
