validate_graph_ids | . as $detail | .summary.uuid as $room | subscriptions as $all_routes |
([.users[] | select((.userId | user_key | @uri) == $selected)] | first) as $selected_user |
if $selected_user == null then {nodes: [], edges: []} else
($selected_user.userId | user_key) as $selected |
([.sources[] | select((.ownerUserId | user_key) == $selected) | .sourceId]) as $published |
([$all_routes[] | select((.receiver.userId | user_key) == $selected or (.route.sourceId as $id | $published | index($id)))]) as $routes |
($published + [$routes[].route.sourceId] | unique) as $source_ids |
([.sources[] | select(.sourceId as $id | $source_ids | index($id))]) as $sources |
([$selected] + [$sources[].ownerUserId | user_key] + [$routes[].receiver.userId | user_key] + [$routes[].route.producerUserId | user_key] | unique) as $user_keys |
([.users[] | select((.userId | user_key) as $key | $user_keys | index($key))]) as $users |
([$users[].transport.mediaWorkerId] | unique) as $workers |
{
    nodes: ([$users[] | user_node($room; $selected)] + [
        $user_keys[] | select(. as $key | [$users[].userId | user_key] | index($key) | not) | missing_user_node($room)
    ] + [$workers[] as $worker |
        [$detail.users[] | select(.transport.mediaWorkerId == $worker)] as $worker_users |
        {
            id: ($worker | worker_id), title: "worker \($worker)", subTitle: "media worker",
            mainStat: "\($worker_users | length) users",
            secondaryStat: "\([$worker_users[].publications[]] | length) pub / \([$worker_users[].subscriptions[]] | length) sub"
        }
    ] + [$sources[] as $source |
        $source | source_node($room; ([$all_routes[] | select(.route.sourceId == $source.sourceId)] | length))
    ] + [
        $source_ids[] | select(. as $id | [$sources[].sourceId] | index($id) | not) | missing_source_node($room)
    ]) | unique_by(.id),
    edges: ([$users[] | {
        id: "transport:\($room):\(.userId | user_key)",
        source: user_id($room; .userId), target: (.transport.mediaWorkerId | worker_id),
        mainStat: "transport", secondaryStat: (.transport.health // "unknown"),
        detail__connection: (.transport.connectionId | tostring)
    }] + [$sources[] as $source |
        ([$users[] | select((.userId | user_key) == ($source.ownerUserId | user_key))] | first) as $owner |
        {
            id: "publish:\($room):\($source.sourceId)",
            source: (if $owner == null then user_id($room; $source.ownerUserId) else ($owner.transport.mediaWorkerId | worker_id) end),
            target: source_id($room; $source.sourceId),
            mainStat: "\($source.streamId | stream_label) upload", secondaryStat: "\($source.currentIncomingBitrateBps) bps", color: "blue",
            detail__owner_user: ($source.ownerUserId | user_key)
        }
    ] + [$routes[] | .receiver as $receiver | .route |
        (if ($receiver.userId | user_key) == $selected then "inbound" else "outbound" end) as $direction |
        (subscription_details + {
            id: "deliver:\($room):\(.sourceId):\($receiver.userId | user_key)",
            source: source_id($room; .sourceId), target: ($receiver.transport.mediaWorkerId | worker_id),
            detail__receiver_user: ($receiver.userId | user_key), detail__direction: $direction
        }), {
            id: "consume:\($room):\(.sourceId):\($receiver.userId | user_key)",
            source: ($receiver.transport.mediaWorkerId | worker_id), target: user_id($room; $receiver.userId),
            mainStat: "consume", secondaryStat: .state, color: (.state | route_color), detail__direction: $direction
        }
    ]) | unique_by(.id)
}
end
