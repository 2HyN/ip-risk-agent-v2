import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Page } from "../shared/api/types";
import { usePagedResource } from "../shared/hooks/use-paged-resource";

type Item = { id: string };

afterEach(cleanup);

function Harness({ loader }: { loader: (cursor: string | null) => Promise<Page<Item>> }) {
  const resource = usePagedResource(loader, [loader]);
  if (resource.loading) return <p>Loading</p>;
  return (
    <div>
      <ol>
        {resource.data?.items.map((item) => <li key={item.id}>{item.id}</li>)}
      </ol>
      <button disabled={resource.loadingMore} onClick={resource.loadMore}>Load more</button>
    </div>
  );
}

describe("usePagedResource", () => {
  it("consumes an opaque next cursor and appends the next page", async () => {
    const loader = vi.fn(async (cursor: string | null): Promise<Page<Item>> =>
      cursor === null
        ? { items: [{ id: "first" }], next_cursor: "signed-cursor" }
        : { items: [{ id: "second" }], next_cursor: null },
    );
    render(<Harness loader={loader} />);
    expect(await screen.findByText("first")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("second")).toBeInTheDocument();
    expect(loader).toHaveBeenNthCalledWith(1, null);
    expect(loader).toHaveBeenNthCalledWith(2, "signed-cursor");
  });
});
