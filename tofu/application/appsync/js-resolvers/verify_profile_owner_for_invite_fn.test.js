// The three verify_profile_owner_for_* resolvers share one contract, asserted
// once in lib/verify_profile_owner_cases.js. This file only says which family
// runs the shared spec.
import { describeVerifyProfileOwnerFamily } from './lib/verify_profile_owner_cases.js';

describeVerifyProfileOwnerFamily('invite');
