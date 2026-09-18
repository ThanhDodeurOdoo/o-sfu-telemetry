validate_graph_ids | .summary.uuid as $room | subscriptions as $routes |
([.users[].userId | user_key]) as $users |
([.sources[].sourceId]) as $sources |
{
    nodes: ([{
        id: "room:\($room)", title: $room[0:8], subTitle: "room",
        mainStat: "\(.summary.userCount) sessions",
        secondaryStat: "\(.summary.publicationCount) pub / \(.summary.subscriptionCount) sub",
        detail__worker: (.summary.mediaWorkerId | tostring),
        detail__recording: (.summary.recordingState.recording | tostring),
        detail__transport: "\(.summary.transport.connectedUsers) conn / \(.summary.transport.disconnectedUsers) disc / \(.summary.transport.unknownUsers) unk"
    }] + [.users[] | user_node($room; null)] + [
        .sources[] as $source |
        $source | source_node($room; ([$routes[] | select(.route.sourceId == $source.sourceId)] | length))
    ] + [
        .sources[].ownerUserId | user_key | select(. as $key | $users | index($key) | not) | missing_user_node($room)
    ] + [
        $routes[].route.sourceId | select(. as $id | $sources | index($id) | not) | missing_source_node($room)
    ]) | unique_by(.id),
    edges: ([.users[] | {
        id: "member:\($room):\(.userId | user_key)", source: "room:\($room)", target: user_id($room; .userId),
        mainStat: (.transport.health // "unknown"), color: (.transport.health | health_color)
    }] + [.sources[] | {
        id: "publish:\($room):\(.sourceId)", source: user_id($room; .ownerUserId), target: source_id($room; .sourceId),
        mainStat: "\(.streamId | stream_label) upload", secondaryStat: "\(.currentIncomingBitrateBps) bps", color: "blue"
    }] + [$routes[] | .receiver as $receiver | .route |
        subscription_details + {
            id: "download:\($room):\(.sourceId):\($receiver.userId | user_key)",
            source: source_id($room; .sourceId), target: user_id($room; $receiver.userId)
        }
    ]) | unique_by(.id)
}
