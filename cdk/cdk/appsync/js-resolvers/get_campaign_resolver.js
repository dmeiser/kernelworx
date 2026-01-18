export function request(ctx) {
    return {};
}

export function response(ctx) {
    const campaign = ctx.prev.result;
    // Ensure isActive has a default value for backward compatibility (handles null and undefined)
    if (campaign && campaign.isActive == null) {
        campaign.isActive = true;
    }
    return campaign;
}
