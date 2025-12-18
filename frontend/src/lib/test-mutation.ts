import { gql } from "@apollo/client";

// This is to test if deleteProfileInvite works despite schema showing as failed
export const TEST_DELETE_PROFILE_INVITE = gql`
  mutation DeleteProfileInvite($inviteCode: ID!) {
    deleteProfileInvite(inviteCode: $inviteCode)
  }
`;
